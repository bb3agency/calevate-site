> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Agent

> Changes any subset of the fields Create Agent takes and answers with the whole agent. Fields you leave out are untouched, and unknown fields are ignored — but a body that names no field this API knows is refused. A model or voice is checked against your plan only when it changes, and a refused voice refuses the whole patch before anything is written. A **build** key may do this.



## OpenAPI

````yaml /api-reference/openapi.json patch /agents/{id}
openapi: 3.1.0
info:
  title: ThinnestAI API
  version: 1.0.0
  description: >-
    Build voice and WhatsApp agents, place calls, message customers and run a
    platform of your own customers on one API.
servers:
  - url: https://app.thinnest.ai/api/v1
    description: Production
security:
  - bearerAuth: []
tags:
  - name: Agents
    description: >-
      An agent is one assistant with its instructions, model, languages, website
      widget and call settings — the same thing the console's Agent page builds.
      Create one here, then give it knowledge, actions and channels.
  - name: Knowledge
    description: >-
      The documents an agent searches and cites when it answers — a web page or
      pasted text, split into passages and indexed. Use it for facts (prices,
      policies, opening hours) rather than putting them in the instructions.
  - name: Actions
    description: >-
      Calls to your own HTTPS API that an agent can make mid-conversation, with
      arguments it fills from what the customer said — how an agent uses data
      that stays in your own system. Create one, test it, then switch it on.
  - name: Tools
    description: >-
      Everything else an agent can do besides answer: its built-in tools, the
      MCP tool servers it is connected to, and the accounts it works in
      (calendar, spreadsheets, CRMs, records kept here, helpdesks). Every tool
      starts off.
  - name: Channels
    description: >-
      Where an agent answers: the website widget, WhatsApp, Telegram and calls.
      Read an agent's channels here and connect a Telegram bot; WhatsApp is
      connected in the console, because Meta's sign-up runs in the business
      owner's own browser.
  - name: Calls
    description: >-
      A call is one phone, web or WhatsApp conversation with an agent — one you
      placed through the API, a campaign's, or one a customer made to you. Place
      calls here, one at a time or in a batch, and read each one back with its
      summary, collected details and transcript.
  - name: Post-call
    description: >-
      What happens after a call ends: the outcome, a short summary and the
      details the agent collects. Read a call's analysis here, and set what an
      agent does after every call.
  - name: Recordings
    description: >-
      A call's audio, for agents that record their calls. Fetch it with your
      key, or hand a CRM user the signed link a call report carries — that one
      needs no key.
  - name: Conversations
    description: >-
      A conversation is one customer's thread with your workspace on one channel
      — WhatsApp, the web widget, Telegram, voice or email. Read threads and
      their messages (including to catch up on a webhook you missed), answer a
      WhatsApp customer from your own agent platform, and resolve, take over or
      assign threads as the inbox does.
  - name: Messages
    description: >-
      Send one approved WhatsApp template to one customer, because something
      happened in your own system — an order confirmation, a delivery update, an
      appointment reminder. No agent is needed: this is how your software starts
      a WhatsApp conversation.
  - name: One-time codes
    description: >-
      Deliver a login or verification code you generated over WhatsApp, without
      handling templates yourself, and set up the authentication templates it
      sends with. WhatsApp writes these messages — "*394812* is your
      verification code." — so you choose only the expiry, the security line and
      the button.
  - name: Contacts
    description: >-
      The people your workspace knows — kept in step with your CRM by phone
      number and your own `externalId`, with marketing consent recorded
      alongside where it came from.
  - name: Do not call
    description: >-
      Numbers your agents must never ring. Every outbound call refuses a number
      on this list — Create Call answers `409`, a batch refuses that entry, a
      calling campaign skips the person and records why, and a booked callback
      is given up — while inbound calls from it are answered as usual. The same
      list as **Contacts → Do not contact** in the console, and the one your
      voice agent adds to on its own when a caller asks not to be called again
      (in any language), which also sends the `contact.opted_out` webhook event.
  - name: Events
    description: >-
      Tell us something happened in your system — `order.delivered`,
      `trial.ended` — and the sequences and tags you set up in the console
      decide what follows. Your code says what happened; the console says what
      happens next.
  - name: Templates
    description: >-
      WhatsApp message templates: the pre-approved messages your business may
      send to a customer first, or outside the 24 hours after they last wrote. A
      template is saved as a draft, sent to WhatsApp for review, and can be sent
      (Send Message, Create Campaign) only once it is `approved`. Templates are
      named, not numbered, and one name can exist in several languages.
  - name: Campaigns
    description: >-
      A campaign sends one thing to many people. It is either a WhatsApp
      **broadcast** (`kind: "whatsapp"`), which sends one approved template to
      everyone in its audience, or a **calling campaign** (`kind: "voice"`),
      where an agent phones each person from its own number within the hours you
      set. Who is in the audience is decided by consent, exactly as in the
      console, and every campaign is created as a draft that you then launch,
      schedule, pause, resume or cancel.
  - name: Sequences
    description: >-
      A sequence sends one person several approved WhatsApp templates over days
      — "your order shipped", then "how was it?" two days later — and stops by
      itself when they reply, are tagged, or an event says so. People join by
      tag, by event, or one at a time through Enrol in Sequence. Sequence ids
      are bare uuids.
  - name: Forms
    description: >-
      A WhatsApp form is a screen your customer fills in without leaving the
      chat — a delivery address, an appointment request, a short survey. Build
      it here, publish it to your own WhatsApp Business Account, then send it
      from a template's button, an agent, the inbox or Reply to Conversation.
  - name: Phone numbers
    description: >-
      The numbers your agents answer and call from. A workspace holds them two
      ways: numbers it **rents** here, charged every month from your balance,
      and numbers it **brings** from its own carrier account, which we never
      bill. Each number is answered by at most one agent (its line) and may be
      lent to one agent to call out on. A number is named by the number itself,
      in any spelling: `918041234567`, `+918041234567` and `%2B918041234567` in
      a path are the same number.
  - name: SMS
    description: >-
      Your own SMS provider and your own DLT registration, so your agents can
      text customers in India — during a call (the `send_sms` built-in tool) and
      after it (an agent's post-call `followUp`). Every business SMS in India
      must match a template approved on your DLT portal and go out under your
      six-letter sender header; your provider bills you for each one, and
      nothing is charged to your wallet here. Providers: `msg91`, `exotel`,
      `gupshup` (Enterprise SMS), `infobip`, `vonage`, `fast2sms`. On your DLT
      portal, add your provider as your telemarketer (the PE–TM chain) or every
      send is rejected.
  - name: Voices
    description: >-
      The voices an agent can speak with, as the console's voice picker lists
      them. An item's `id` is what an agent's `voice.voice` takes.
  - name: Voice clones
    description: >-
      Your workspace's own cloned voices, made from a short recording with the
      speaker's consent. A clone is listed with the Studio voices and can be put
      on an agent like any other voice.
  - name: Models
    description: >-
      The language models an agent can answer with, as the console names them.
      An item's `id` is what an agent's `model` takes.
  - name: Bring your own keys
    description: >-
      Run your agents on your own provider accounts and pay a flat platform fee
      instead of our usage rates. Bring all three keys (speech-to-text, LLM,
      voice): ₹0.02 a chat reply and ₹1 a call minute, all-in. Or bring only
      your voice key (scope voice): our speech-to-text, model and telephony, a
      call billed at the voice-only BYOK rate (₹1.50 / $0.02 a minute by
      default), which includes our model — so calls run only on Prana, Prana
      [Voice], GPT-OSS 120B or another model GET /api/v1/models marks
      `voiceOnlyByok` (an agent on any other model runs on Prana on calls) —
      chat replies as usual, on any model. Or bring your language-model key and
      your voice key (scope llm_voice): we keep the speech recogniser, a call is
      a flat ₹1 a minute like all three keys, with no model limit, and a chat
      reply is the same flat fee. Or bring only your language-model key (scope
      llm): we keep the speech recogniser and the voice, and a call is billed
      exactly like any other call on the voice plan the agent speaks with —
      Standard, Premium or Studio, with your plan's discount — whatever model
      your key runs, with no model limit; chat replies are billed at the same
      flat own-keys fee as under all three keys. There is no fallback to our
      providers when one of your keys fails. The switch and the default `scope`
      are per workspace, and each agent follows them by default. Each agent can
      choose for itself (Create Agent, Update Agent `byok`): `null` follows the
      workspace, `"off"` runs that one agent on our voices and models at our
      normal pricing — chat replies billed normally, the voice-only model limit
      not applied — and a scope (`all`, `voice`, `llm` or `llm_voice`) runs it
      on that scope's keys, so one workspace with an LLM key and a voice key can
      have one agent on `llm` and another on `llm_voice`. A scope is refused
      (409, naming the missing key) unless you hold verified keys for it, and a
      key an agent's scope needs cannot be removed while BYOK is on. If a key is
      gone when a call starts, the agent falls back to the workspace's scope,
      never fails the call. A call is priced and run on one stack: the agent's
      setting is read once when the call or reply starts.
  - name: Webhooks
    description: >-
      Endpoints an agent's events are sent to as they happen — a CRM, a sheet,
      Slack, Zapier, or a helpdesk email address. Each delivery is a signed JSON
      `POST` of `{ "id", "event", "sentAt", "data" }`.


      **Headers on every attempt** (not sent to an email destination, which gets
      one ticket email per event)


      | Header | What it is |

      |---|---|

      | `x-thinnest-signature` | `sha256=<hex HMAC-SHA256 of the raw body>`
      under the endpoint's signing secret. |

      | `x-thinnest-signature-v2` | `sha256=<hex HMAC-SHA256 of
      "<x-thinnest-delivered-at>.<raw body>">` — the delivery time, signed. |

      | `x-thinnest-delivered-at` | When this attempt left (ISO 8601). |

      | `x-thinnest-event-id` | `evt_…`, the same as the body's `id` — stable
      across every retry and re-send. |

      | `x-thinnest-attempt` | `1` for the first attempt, then `2`, `3`, … |


      **Retries.** A delivery that fails — any answer other than 2xx, a timeout
      after 10 seconds, or an address we cannot reach — is tried again after 1
      minute, 5 minutes, 30 minutes, 2 hours and 6 hours (six attempts over
      about 8½ hours). Every attempt sends the **same bytes**, so `sentAt` is
      when the event happened, not when the attempt left. Payloads are kept for
      7 days; within that time any failed delivery can be sent again with
      Redeliver Webhook Events.


      **Dedupe** on `x-thinnest-event-id` (or the body's `id`): a retry after a
      timeout can reach you after you already processed the first attempt.
      Answer 2xx quickly and do the work afterwards.


      **Freshness.** To refuse replayed requests, verify
      `x-thinnest-signature-v2` and reject an `x-thinnest-delivered-at` more
      than five minutes from your clock. Do not check freshness on `sentAt`: a
      retry's `sentAt` is hours old by design.


      **Switch-off.** An endpoint is switched off after five events in a row
      that each failed every attempt — single failed attempts that later succeed
      do not count. Events that happen while it is off are recorded as not sent;
      switch it back on and re-send them.


      **Ids in `data`** are the prefixed ids the API returns and takes:
      `conversationId` is `conv_…` (the conversation endpoints take it),
      `campaignId` is `cmp_…`, and a call is `out_…`, `sch_…` or its call
      reference (Get Call takes it). The `WebhookPayload` schema has a full
      example of every event's body.


      The events an endpoint can subscribe to:


      | Event | When it fires |

      |---|---|

      | `lead.captured` | The agent collected a name, email or phone from
      somebody who showed real interest. |

      | `conversation.escalated` | The agent handed a conversation to a person —
      asked for, or because it could not answer. |

      | `conversation.resolved` | A teammate marked a conversation done. |

      | `call.completed` | A call the agent placed or answered ended — how it
      ended and how long it lasted, sent the moment it ends. |

      | `call.analysed` | A call's results are ready: its summary, the details
      it collected, the transcript, a recording link and what the call cost
      (`costMicro`, `currency`) — the same shape as Get Call. |

      | `campaign.finished` | Every person on a broadcast or a calling campaign
      has been reached, or given up on. |

      | `contact.opted_out` | During a call, somebody asked not to be called
      again; their number (`data.phone`) is now on the do-not-call list;
      `data.source` is `"call"`; `data.reason` is the words they used, as
      recorded, or null. |

      | `call.problem` | During a call: the agent could not answer, your own
      model key failed, a reply was very slow, or the voice connection failed.
      Sent once per kind per call. |

      | `contact.erased` | A contact you deleted is gone completely, recordings
      included — at once, or after the nightly retry when a recording could not
      be deleted straight away (`recordingsPending`). Sent once. |

      | `byok.changed` | Your own keys changed: a key was added, replaced,
      removed or failed its check, or your own keys were switched on or off or
      set to cover different jobs. |


      **`call.problem`** is sent while the call is still going on, at most once
      per kind per call: `data` is `{ "callId", "agentId", "kind", "detail",
      "at" }`, where `callId` is the id Get Call takes and `kind` is
      `no_answer_from_model` (the agent could not get an answer and apologised
      to the caller), `byok_failed` (your own model key failed), `slow_reply` (a
      reply took more than 5 seconds to start) or `voice_failed` (the call's
      voice connection failed). `detail` is a sentence to show a person.


      **Calls handed to another agent.** `lead.captured` and
      `conversation.escalated` carry `data.agentId` (the agent that ran the
      tool) and `data.callId` (the id Get Call takes; null off a call). On a
      call handed to another agent the call-level events — `call.completed`,
      `call.analysed`, `call.problem` — stay with the agent the call started
      with, and `handedTo` on `call.analysed` and Get Call lists the others, so
      `callId` joins them. Each `handedTo` entry says whether the hand-off was
      `warm` or `cold` (`mode`) and, when warm, the `summary` the next agent was
      given. A hand-off to another agent is not a hand-over to a person and
      sends no `conversation.escalated`.


      **Usage and billing per call.** `call.analysed` carries `data.usage` and
      `data.billing`, the same objects as Get Call's: `inputTokens`,
      `outputTokens` and `cachedInputTokens` the call's replies used (your own
      model key's too), `inputTokensEstimated` (true when part of the input
      count was estimated because the provider reported none) and
      `ttsCharacters` (text sent to the voice, including text sent before the
      caller interrupted); and `billing` — whose keys the call ran on (`keys`),
      the voice plan it was priced on (`voicePlan`), its per-minute rate
      (`ratePerMinuteMicro`) and the seconds it was charged for
      (`billedSeconds`).


      **Workspace events.** `contact.erased` and `byok.changed` are about the
      whole workspace, not one agent. They go to every endpoint in the workspace
      that subscribed to them, whichever agent it was added on — once per
      address, so three agents posting to the same URL still receive one
      delivery — and to a developer's every-customer endpoints
      (`includeCustomers`) for an event in one of its customers. An endpoint
      subscribed to every event (`["*"]`) receives them too. Neither carries
      personal data or key material:


      - `contact.erased`: `data` is `{ "contactId", "erasedAt" }` — the `cust_…`
      id Delete Contact was given and when it was erased. Sent exactly once:
      straight after Delete Contact when it answered 204, or from the nightly
      retry once the last recording it reported as `recordingsPending` is gone
      (a recording still being written can take up to three nights to be
      confirmed).

      - `byok.changed`: `data` is `{ "change", "kind", "provider",
      "byokEnabled", "scope" }`. `change` is `key_added`, `key_replaced`,
      `key_removed`, `key_failed_verification` (the provider refused a key you
      tried to save; nothing was saved), `byok_enabled`, `byok_disabled` or
      `scope_changed`. `kind` (`stt`, `llm` or `tts`) and `provider` name the
      key for the four key changes and are null for the others. `byokEnabled`
      and `scope` are where the workspace stands after the change. A change of a
      key's model is not sent, and saved keys are not re-checked on a schedule:
      a model key that stops working on a call shows up as `call.problem`
      (`byok_failed`).


      **Call quality.** `call.completed` and `call.analysed` carry
      `data.quality`, the same object as Get Call's `quality`: reply times
      (`responseMs` from the caller falling silent to the agent's first audio,
      `firstTokenMs` our side of it — each median, p90 and max in milliseconds),
      long silences, interruptions, and the turns the agent apologised for
      (`modelErrors`) or a backup model answered (`rescues`). It is null for a
      call that was not measured, and on `call.completed` when the call ended
      before its figures arrived — `call.analysed` and Get Call have them by
      then.
  - name: Usage
    description: >-
      Read what your workspace used and spent — replies, calls, WhatsApp, the
      balance history and invoices — the same figures as the console's Usage and
      Billing pages. All reads.
  - name: Analytics
    description: >-
      The Dashboard's counts and each agent's Analytics page, for building a
      dashboard of your own that agrees with the console.
  - name: Customers
    description: >-
      Workspaces you create for your own customers when you build a product on
      this API. Each customer has its own agents, contacts, knowledge, phone
      numbers and WhatsApp; your one key reaches any of them by adding
      `Thinnest-Workspace: <customer id>` to a request, and everything they use
      is charged to you. Manage customers from your own workspace, without that
      header.
  - name: Workspace
    description: >-
      Your workspace's own settings — its name and time zone — as Settings →
      General shows them. With `Thinnest-Workspace`, the customer's workspace
      instead.
  - name: Projects
    description: >-
      Projects group a workspace's agents, and are what a team's access is
      scoped by. Every workspace has a default project that cannot be deleted; a
      second project needs a plan with teams and projects.
  - name: Teams
    description: >-
      Teams are groups of members and the projects they can reach. A project
      granted to no team is open to the whole workspace; granting it to a team
      restricts it to that team's members (owners and admins always see
      everything), and removing its last grant opens it up again.
  - name: Members
    description: >-
      The people in your workspace and their roles. An API key acts as an admin,
      never an owner: it can make people admins or members and remove them, but
      cannot make anybody an owner, and the last owner can be neither demoted
      nor removed.
  - name: Invitations
    description: >-
      Invitations to join your workspace, as Settings → Members sends them: an
      email with a link that works for 14 days. Pending invitations count
      towards your plan's seats.
  - name: Notifications
    description: >-
      What each kind of notification does in your workspace: shown in the
      console's feed or muted, and whether it is emailed through the email
      sender you connected in the console.
  - name: Saved replies
    description: >-
      Sentences your team sends often, offered in the inbox composer as
      `/shortcut`.
  - name: Contact groups
    description: >-
      Named lists of contacts — "Wholesale buyers", "Pune walk-ins" — the same
      groups as **Contacts → Groups** in the console. Aim a broadcast or a
      calling campaign at one with `groups` on Create Campaign. A group narrows
      who a campaign reaches and never widens it: consent still decides, exactly
      as for tags. Deleting a group never deletes its contacts. List a group's
      contacts with List Contacts and `group=grp_…`.
paths:
  /agents/{id}:
    parameters:
      - name: id
        in: path
        required: true
        description: >-
          The agent's id (`ag_…`), as List Agents returns it. Another
          workspace's agent is the same `404` as one that never existed.
        schema:
          type: string
        example: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
    patch:
      tags:
        - Agents
      summary: Update Agent
      description: >-
        Changes any subset of the fields Create Agent takes and answers with the
        whole agent. Fields you leave out are untouched, and unknown fields are
        ignored — but a body that names no field this API knows is refused. A
        model or voice is checked against your plan only when it changes, and a
        refused voice refuses the whole patch before anything is written. A
        **build** key may do this.
      operationId: updateAgent
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/AgentUpdateRequest'
            example:
              greeting: >-
                Namaste! Skyline Homes here — is this a good time to talk about
                Sky Towers?
              temperature: 0.4
              widget:
                accent: '#0f766e'
              voice:
                pastConversations: recap
                detectMachines: true
      responses:
        '200':
          description: The agent after the change.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Agent'
              example:
                id: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
                name: Skyline Sales
                instructions: >-
                  You call people who enquired about a flat at Sky Towers,
                  Baner. Find out their budget, preferred size and when they can
                  visit the site.
                greeting: >-
                  Namaste! Skyline Homes here — is this a good time to talk
                  about Sky Towers?
                businessDescription: Skyline Homes builds 2 and 3 BHK apartments in Pune.
                model: prana-voice
                temperature: 0.4
                maxReplyTokens: 300
                language: Hindi
                secondLanguage: null
                escalation:
                  onNoAnswer: false
                  onRequest: true
                captureLeads: true
                scheduleCallbacks: false
                steps: []
                widget:
                  theme: classic
                  accent: '#0f766e'
                  height: 806
                  welcomeScreen: true
                  welcomeCollectLeads: true
                voice:
                  answersCalls: true
                  surfaces:
                    - web
                    - whatsapp
                    - phone
                  voice: priya
                  phoneNumber: '+918047361290'
                  language: null
                  summariseCalls: true
                  detectMachines: true
                  recordCalls: true
                  maxCallSeconds: 300
                  pastConversations: recap
                  unavailableMessage: null
                  unavailableMessageNote: null
                  callStartUrl: null
                  thinking: true
                  thinkingLines: []
                  thinkingDelayMs: 900
                  thinkingRepeatMs: 2500
                  thinkingAtTurnEnd: false
                  turnSilenceSeconds: null
                  turnDetection: null
                  recordDoNotCall: true
                  interruptWords: 3
                  neverInterrupt: false
                  holdShortSpeech: true
                  greetingUninterruptible: false
                  ambience: null
                  ambienceVolume: 0.15
                  endCallOnFinish: false
                  nudgeAfterSeconds: null
                  nudges: 1
                  nudgePhrase: null
                  endAfterSilenceSeconds: null
                  endPhrases: []
                  callInstructions: null
                byok: workspace
                collectFields: []
                webKey: pk_9fQ2xLm7Rt4vWb8KcN3hYd6sJ1pZ
                createdAt: '2026-09-17T09:39:31.204Z'
        '400':
          description: >-
            A field breaks its rule, the body names nothing to change, or the
            new model or voice is not one you may use.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                empty:
                  summary: Nothing to change
                  value:
                    error: >-
                      Nothing to change — the body named no field this API
                      knows.
                slow:
                  summary: Model too slow for calls
                  value:
                    error: That model is too slow to answer a call. Pick another.
                voiceOnly:
                  summary: A voice-only model
                  value:
                    error: >-
                      That model cannot be picked as an agent's model. Pick
                      another.
                seconds:
                  summary: Call length out of range
                  value:
                    error: '`voice.maxCallSeconds` must be between 60 and 1200.'
                language:
                  summary: Unknown language
                  value:
                    error: >-
                      `language` must be "auto" or a language the console
                      offers, e.g. "Hindi".
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: No such agent in your workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That agent was not found.
        '409':
          description: >-
            `voice.surfaces` adds `phone` while the agent answers calls and has
            no phone number to answer or call from. The `code` is
            `phone_number_required`; attach a number first, or switch
            `answersCalls` off while you set it up. Nothing was saved.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  `voice.surfaces` includes `phone`, but this agent has no phone
                  number. Attach one first.
                code: phone_number_required
        '410':
          $ref: '#/components/responses/WorkspaceDeleted'
        '429':
          $ref: '#/components/responses/TooManyRequests'
        '500':
          description: >-
            Part of the change was not saved: the fields the agent collects, the
            `voice` settings, or a call-start signing secret. Send the same
            request again; settings that were saved before the failure are kept.
            The fields the agent collects are written first, so when they fail
            the voice settings were not applied and nothing is lost by repeating
            the request. A new signing secret is shown once, on the response
            that creates it: if a secret was created it is not shown, and the
            message says so. Send `voice.callStartSecret: "rotate"` for a new
            one (repeating the same `callStartUrl` creates nothing, because the
            address has not changed).
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                voice:
                  summary: Voice settings not saved
                  value:
                    error: The voice settings could not be saved. Try again.
                    code: internal_error
                fields:
                  summary: Collected fields not saved
                  value:
                    error: >-
                      Saved the agent, but not the fields it collects, and its
                      voice settings were not applied. Send the same request
                      again.
                    code: internal_error
                secret:
                  summary: Signing secret not shown
                  value:
                    error: >-
                      The call-start address was saved, but its signing secret
                      could not be created. Send `voice.callStartSecret:
                      "rotate"` to get a new one.
                    code: internal_error
        '503':
          description: >-
            A `voice.callStartUrl` (or `voice.callStartSecret: "rotate"`) was
            sent but call-start requests cannot be signed right now, so nothing
            was saved. The `code` is `signing_unavailable`; try again later.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  Call-start lookups cannot be signed on this deployment yet, so
                  the address was not saved.
                code: signing_unavailable
components:
  parameters:
    Workspace:
      name: Thinnest-Workspace
      in: header
      required: false
      description: >-
        Developers only: the customer workspace this request acts in — its
        `org_…` id from `POST /customers`. Leave it out to act in your own
        workspace. Refused with `404` (`Workspace not found.`) when the id is
        unknown, is not one of your customers, or is not an `org_…` id; `410`
        when that customer was deleted (restore it with `POST
        /customers/{id}/restore` until it is erased); `403` when the key belongs
        to one customer workspace (it cannot act as another); `400` when your
        workspace is not a developer workspace. `/customers/*` and `GET
        /customers/usage` are your own workspace's and refuse the header with
        `400`: call them without it.
      schema:
        type: string
        example: org_3fKq9TzQ1mN8vB2xR7cLpA
  schemas:
    AgentUpdateRequest:
      type: object
      description: >-
        Any subset of the agent's fields. At least one must be a field this API
        knows.
      properties:
        name:
          type: string
          minLength: 2
          maxLength: 60
          description: >-
            The agent's name, 2 to 60 characters, without hidden characters or
            markup.
        instructions:
          type: string
          maxLength: 20000
          description: >-
            What the agent is and how it behaves. Re-sent on every reply, so
            every character costs on every turn.
        greeting:
          type: string
          maxLength: 200
          description: >-
            The first thing it says on a call or in a chat. An empty string
            clears it.
        businessDescription:
          type: string
          maxLength: 200
          description: One line about what the business is. Facts belong in Knowledge.
        model:
          type:
            - string
            - 'null'
          description: >-
            A model id from List Models, or `null` to put the agent back on the
            default model (Prana [Voice]) — the way back to the defaults; the
            plan and call rules below still apply to it. An empty string is a
            400. Checked only when it changes, against the console's one model
            picker for chat and calls alike: on your plan, quick enough to
            answer a call (`voice: true`), within the per-minute budget a call
            can carry, and not one of our voice-only models. A chat-only agent
            is held to the same list, as in the console.
        temperature:
          type: number
          minimum: 0
          maximum: 2
          description: How adventurous the wording is. Clamped to 0–2.
        maxReplyTokens:
          type: number
          minimum: 100
          maximum: 800
          description: >-
            The longest a reply may be, in tokens, for chat and calls alike.
            Rounded and clamped to 100–800.
        language:
          type: string
          description: >-
            `auto` to reply in the customer's language, or a language the
            console offers by its English name, e.g. `Hindi`, `Tamil`,
            `English`.
        secondLanguage:
          type:
            - string
            - 'null'
          description: >-
            Retired. Accepted so an older integration keeps working, but
            ignored: the agent answers in `language` alone.
          deprecated: true
        escalation:
          $ref: '#/components/schemas/AgentEscalationInput'
        captureLeads:
          type: boolean
          description: Take a name, email or phone number from an interested customer.
        scheduleCallbacks:
          type: boolean
          description: Allow it to book a call back when asked.
        welcomeScreen:
          type: boolean
          description: Open the website widget on a welcome screen.
        welcomeCollectLeads:
          type: boolean
          description: Ask for the visitor's details on the welcome screen.
        steps:
          type: array
          maxItems: 12
          description: >-
            The conversation script, in order, replacing the whole script. `[]`
            removes it.
          items:
            $ref: '#/components/schemas/AgentStepInput'
        byok:
          type:
            - string
            - 'null'
          enum:
            - workspace
            - 'off'
            - all
            - voice
            - llm
            - llm_voice
            - null
          description: >-
            How this agent uses the workspace's own provider keys (Bring your
            own keys). `null` (or `workspace`) follows the workspace: its
            default scope applies when it brings its own keys. `off` never does:
            our voices and models at our normal pricing, whatever the workspace
            does, and the model is not held to the voice-only-BYOK model list.
            `all`, `voice`, `llm` or `llm_voice` runs this agent on that scope's
            keys whatever the workspace default is; refused with `409` naming
            the missing key unless the workspace holds verified keys for every
            kind that scope needs. If a key goes later, the agent falls back to
            the workspace's scope at the next call. Omit the field to leave it
            unchanged; saved BYOK model and voice choices are kept but not used
            while it is `off`. Read back as `workspace` when it follows the
            workspace.
        widget:
          $ref: '#/components/schemas/AgentWidgetInput'
        voice:
          $ref: '#/components/schemas/AgentVoiceInput'
        collectFields:
          type:
            - array
            - 'null'
          maxItems: 30
          description: >-
            The details to fill in after every call, replacing the list. `[]` or
            null stops collecting; records already taken are kept.
          items:
            $ref: '#/components/schemas/AgentCollectFieldInput'
    Agent:
      type: object
      description: An agent as the console shows it.
      required:
        - id
        - name
        - instructions
        - greeting
        - businessDescription
        - model
        - temperature
        - maxReplyTokens
        - language
        - secondLanguage
        - escalation
        - captureLeads
        - scheduleCallbacks
        - steps
        - widget
        - voice
        - byok
        - collectFields
        - webKey
        - createdAt
      properties:
        id:
          type: string
          description: The agent's id.
          example: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
        name:
          type: string
          description: The agent's name, 2 to 60 characters.
        instructions:
          type: string
          description: What the agent is and how it behaves — its standing prompt.
        greeting:
          type: string
          description: The first thing it says, or an empty string.
        businessDescription:
          type: string
          description: One line about the business, or an empty string.
        model:
          type:
            - string
            - 'null'
          description: >-
            A model id from List Models. `null` when the agent is on a model
            that has since been retired.
        temperature:
          type: number
          minimum: 0
          maximum: 2
          description: How adventurous the wording is.
        maxReplyTokens:
          type: integer
          minimum: 100
          maximum: 800
          description: >-
            The longest a reply may be, in tokens — one ceiling for chat and
            calls.
        language:
          type: string
          description: >-
            `auto` (reply in the customer's language) or the language it always
            replies in, e.g. `Hindi`.
        secondLanguage:
          type:
            - string
            - 'null'
          description: >-
            Retired — always `null`. An agent answers in one language,
            `language`. Still returned so a client that reads it keeps working.
          deprecated: true
        escalation:
          $ref: '#/components/schemas/AgentEscalation'
        captureLeads:
          type: boolean
          description: >-
            Whether it takes a name, email or phone number from an interested
            customer.
        scheduleCallbacks:
          type: boolean
          description: Whether it may book a call back when asked.
        steps:
          type: array
          description: Its conversation script, in order.
          items:
            $ref: '#/components/schemas/AgentStep'
        widget:
          $ref: '#/components/schemas/AgentWidget'
        voice:
          description: >-
            How it handles calls. `null` when the agent has no voice channel (a
            deployment without voice).
          oneOf:
            - $ref: '#/components/schemas/AgentVoice'
            - type: 'null'
        byok:
          type: string
          enum:
            - workspace
            - 'off'
            - all
            - voice
            - llm
            - llm_voice
          description: >-
            How this agent uses the workspace's own provider keys (Bring your
            own keys). `null` (or `workspace`) follows the workspace: its
            default scope applies when it brings its own keys. `off` never does:
            our voices and models at our normal pricing, whatever the workspace
            does, and the model is not held to the voice-only-BYOK model list.
            `all`, `voice`, `llm` or `llm_voice` runs this agent on that scope's
            keys whatever the workspace default is; refused with `409` naming
            the missing key unless the workspace holds verified keys for every
            kind that scope needs. If a key goes later, the agent falls back to
            the workspace's scope at the next call. Omit the field to leave it
            unchanged; saved BYOK model and voice choices are kept but not used
            while it is `off`. Read back as `workspace` when it follows the
            workspace.
        collectFields:
          type: array
          description: >-
            The details it fills in after every call, in the shape a call's
            `extract` takes. Empty when it collects nothing.
          items:
            $ref: '#/components/schemas/AgentCollectField'
        webKey:
          type:
            - string
            - 'null'
          description: >-
            The public key the website widget embeds (`pk_…`). It is published
            on your site, so it is not a secret.
        createdAt:
          type: string
          format: date-time
          description: When the agent was made.
    Error:
      type: object
      required:
        - error
        - code
      properties:
        error:
          type: string
          description: What went wrong, in a sentence you can show a person.
        code:
          type: string
          enum:
            - unauthorized
            - key_scope_read
            - key_scope_build
            - workspace_not_found
            - workspace_deleted
            - workspace_not_developer
            - workspace_header_forbidden
            - rate_limit_resources
            - rate_limit_family
            - rate_limit_calls
            - rate_limit_messages
            - rate_limit_codes
            - rate_limit_code_recipient
            - concurrent_calls
            - number_daily_limit
            - rate_limited
            - opted_out
            - do_not_call
            - stop_list_unknown
            - insufficient_balance
            - outside_calling_hours
            - number_never_callable
            - call_in_progress
            - call_already_scheduled
            - calling_not_set_up
            - carrier_unavailable
            - agent_not_found
            - agent_ambiguous
            - from_number_invalid
            - agent_on_live_call
            - phone_number_required
            - signing_unavailable
            - invalid_number
            - number_required
            - number_claimed_elsewhere
            - needs_own_carrier_keys
            - number_move_needs_developer
            - number_move_same_workspace
            - number_on_live_call
            - number_move_needs_business_details
            - number_move_carrier_account
            - number_move_unavailable
            - number_move_in_progress
            - number_move_legacy_number
            - number_cannot_forward
            - forward_destination_not_allowed
            - forward_loop
            - template_not_found
            - template_not_approved
            - template_language_missing
            - template_unsendable
            - code_template_not_found
            - code_template_ambiguous
            - whatsapp_not_connected
            - whatsapp_blocked
            - whatsapp_not_configured
            - free_allowance_used
            - send_failed
            - plan_required
            - plan_limit
            - payment_required
            - idempotency_in_progress
            - validation_failed
            - forbidden
            - not_found
            - conflict
            - gone
            - unprocessable
            - internal_error
            - service_unavailable
          description: >-
            A stable machine-readable code. Two refusals that share a status are
            told apart by it (a `403` for an opted-out customer, for the
            do-not-call list and for a key that is not a full key). See the
            table in the API reference under Errors.
        limit:
          type: object
          description: >-
            On a `429` that hit one of our limits: which one and how big it is.
            `perMinute` for a per-minute limit; `max` (and `windowSeconds`) for
            the others.
          required:
            - name
          properties:
            name:
              type: string
              description: >-
                Which limit: `resources`, `family`, `calls`, `messages`,
                `codes`, `code_recipient`, `concurrent_calls` or `number_daily`.
            perMinute:
              type: integer
              description: Requests allowed a minute.
            max:
              type: integer
              description: The most allowed, for a limit that is not per minute.
            windowSeconds:
              type: integer
              description: The window `max` is counted over, when it has one.
      example:
        error: That agent was not found.
        code: not_found
      description: >-
        Every error body. Branch on `code`, never on the sentence in `error`:
        the sentence may be reworded, the code does not change.
    AgentEscalationInput:
      type: object
      description: When the agent hands over to a person. Send either or both.
      properties:
        onNoAnswer:
          type: boolean
          description: Hand over when it cannot answer.
        onRequest:
          type: boolean
          description: Hand over when the customer asks for a person.
      example:
        onNoAnswer: false
        onRequest: true
    AgentStepInput:
      type: object
      description: >-
        One step of the script. A step with neither a title nor a detail is
        dropped.
      properties:
        title:
          type: string
          description: What the step is for. Trimmed and cut to 80 characters.
        detail:
          type: string
          description: What the agent should do here. Trimmed and cut to 600 characters.
        branches:
          type: array
          description: >-
            Conditions within the step, e.g. when `If they are already a
            customer`, action `skip to payment`. A branch missing either half is
            dropped. Returned in `steps` as written.
          items:
            type: object
            properties:
              when:
                type: string
                description: The condition.
              action:
                type: string
                description: What to do when it holds.
        collect:
          type: array
          items:
            type: string
          description: >-
            What must be in hand before the step is done — a name, a date, an
            order number. Returned in `steps`.
      example:
        title: Budget and size
        detail: Ask for their budget and whether they want a 2 BHK or a 3 BHK.
        collect:
          - budget
    AgentWidgetInput:
      type: object
      description: The website widget's look. Send any subset.
      properties:
        theme:
          type: string
          enum:
            - classic
            - modern
          description: The widget's design. Anything else is refused with a 400.
        accent:
          type:
            - string
            - 'null'
          description: >-
            A colour as `#rrggbb` or `#rgb` (the `#` optional). Null or an empty
            string clears it to the default; anything else that is not a colour
            is refused with a 400.
        welcomeScreen:
          type: boolean
          description: >-
            Open the widget on a welcome screen — here, where it is returned, or
            top-level as before.
        welcomeCollectLeads:
          type: boolean
          description: >-
            Ask for the visitor's details on the welcome screen — here or
            top-level.
        height:
          type: number
          minimum: 420
          maximum: 900
          description: The open widget's height in pixels, clamped to 420–900.
      example:
        theme: modern
        accent: '#0f766e'
        height: 720
    AgentVoiceInput:
      type: object
      description: >-
        How the agent handles calls. Send any subset. Where an agent has no
        voice channel yet, sending any of these creates one — switched OFF, so
        setting only a voice or a message never starts it taking calls; send
        `answersCalls: true` to switch it on.
      properties:
        answersCalls:
          type: boolean
          description: Whether the agent takes calls at all.
        voice:
          type:
            - string
            - 'null'
          description: >-
            A voice id from List Voices. A Studio voice needs the Pro plan or
            above. `null` puts the agent back on the default voice a new agent
            starts with (currently Kavya, a Premium voice, which bills at the
            Premium rate) — the way back to the defaults. An empty string is
            refused with a 400.
        language:
          type:
            - string
            - 'null'
          maxLength: 40
          description: >-
            The language for calls: one the console offers, by its English name
            (`Hindi`) or its tag (`hi-IN`), or null to follow the agent's
            `language`. Anything else, `auto` included, is refused with a 400.
        summariseCalls:
          type: boolean
          description: Write a summary after every call (a small charge per call).
        detectMachines:
          type: boolean
          description: Hang up on an answering machine.
        recordCalls:
          type: boolean
          description: Record calls.
        recordDoNotCall:
          type: boolean
          default: true
          description: >-
            Let the agent add a caller to your do-not-call list when they ask
            not to be called again. On by default; `false` takes the ability
            away from this agent, and numbers you add yourself (API, Contacts
            page) are unaffected. In the console: Voice page, Do-not-call list.
        maxCallSeconds:
          type:
            - integer
            - 'null'
          minimum: 60
          maximum: 1200
          description: >-
            The longest a call may run, in whole seconds; null for the default
            ceiling of 20 minutes.
        ringSeconds:
          type:
            - integer
            - 'null'
          minimum: 10
          maximum: 60
          description: >-
            How long a call the agent places (API calls, campaigns, callbacks,
            test calls) rings before it is given up, in whole seconds (10 to
            60); `null` for the default of 30. In the console: Voice page, Ring
            time. A call nobody answers in that time ends as `no_answer` (the
            `hangup` of `call.completed`), and a campaign retries it as one. Can
            be set per call on Place Call.
        pastConversations:
          type: string
          enum:
            - fresh
            - quiet
            - recap
          description: >-
            What a call does with earlier conversations: `quiet` (the default)
            uses them without mentioning it, `recap` opens by recapping them and
            asking whether to carry on, `fresh` uses nothing from before.
        unavailableMessage:
          type:
            - string
            - 'null'
          maxLength: 300
          description: >-
            What a caller hears when this agent's line is switched off
            (`answersCalls` false), instead of the standard "not taking calls"
            sentence. Trimmed, control characters removed, 300 characters at
            most (longer is a 400, not a cut); null or blank clears it. Phone
            calls only. Spoken on Plivo numbers (English, or English in Roman
            letters, but not Hindi) and on Twilio numbers (English and Hindi); a
            Vobiz number gets no message (the call is declined as before), a
            Telnyx number a busy tone and WhatsApp calling a rejection. It is
            read by the provider's own Indian-English voice, so a message in any
            other script, or Hindi on Plivo, plays the standard sentence
            instead. The message is kept either way, and
            `unavailableMessageNote` says when it will not be spoken as written.
            Never used for a call refused over a plan, a balance or busy lines.
        callStartUrl:
          type:
            - string
            - 'null'
          maxLength: 500
          format: uri
          description: >-
            A call-start lookup: an https address of yours, asked who is calling
            when an inbound phone or WhatsApp call is about to be answered by
            the agent (not one forwarded to a person), before the agent speaks.
            We POST `{ "event": "call.started", "callId", "surface": "phone" |
            "whatsapp", "agentId", "from", "to", "direction": "inbound",
            "contact", "sentAt" }` — `to` is the agent's voice line (also on a
            WhatsApp call), and `contact` is the contact you hold under the
            caller's number (`id`, `name`, `phone`, `email`, `externalId`) or
            null — signed like a webhook (`x-thinnest-signature`, and
            `x-thinnest-signature-v2` over `<x-thinnest-delivered-at>.<body>`)
            with the secret returned once as `voice.callStartSecret`. Answer
            within 2 seconds with `{ "variables": { "name": "Asha", "plan":
            "Gold" } }`: up to 20, names normalised and values cut to 150
            characters as for Place Call's `variables`, strings, numbers and
            booleans only. They fill `{{...}}` placeholders in the greeting and
            instructions, over the contact's own fields (yours win). No answer
            in 2 seconds, a non-2xx status or anything else, and the call goes
            ahead without them; we never retry it, but the phone provider asks
            again if it did not get our answer in time, and that repeats the
            request with the same `callId`, so dedupe on `callId`. Must be
            https, not a private address, and carry no username or password.
            `null` or an empty string switches it off and deletes the secret; a
            new address creates a new secret. Refused with `503`
            `signing_unavailable` while call-start requests cannot be signed
            (try again later).
        callStartSecret:
          type: string
          enum:
            - rotate
          description: >-
            Send `"rotate"` to create a new signing secret for the existing
            `callStartUrl` (or the one in the same request); the old one stops
            working at once. The new secret comes back once, as
            `voice.callStartSecret` on the response. Needs a `callStartUrl`. You
            cannot choose the secret yourself.
        surfaces:
          type: array
          items:
            type: string
            enum:
              - phone
              - web
              - whatsapp
          uniqueItems: true
          description: >-
            Where the agent answers calls: `web` (the call button on your
            website), `whatsapp` (WhatsApp calls; whether a WhatsApp number
            takes calls is its own Calls switch on Connect WhatsApp), `phone`
            (its phone number). A new agent starts with `["web", "whatsapp"]`,
            and `phone` is added when a number is attached. Adding `phone` while
            the agent answers calls (`answersCalls` true) and has no number to
            answer or call from is refused with `409` `phone_number_required`;
            with calls off you may set it first and attach a number after. On a
            plan that cannot hold a number, `phone` is left out. While a number
            is attached, `phone` stays on even if you leave it out (a number
            nobody answers is a caller hearing silence): to stop the phone
            ringing, send `answersCalls: false` or take the number off. Anything
            other than these three values is a 400.
          example:
            - web
            - phone
        thinking:
          type: boolean
          default: true
          description: >-
            Say a short filler ("One moment.") when a reply has not started
            after `thinkingDelayMs`, for example while an action runs.
        thinkingLines:
          type:
            - array
            - 'null'
          maxItems: 8
          items:
            type: string
            maxLength: 60
          description: >-
            Your own filler lines, one phrase per item: up to 8, each 60
            characters or fewer after trimming (blank items are dropped; a line
            break inside an item is a 400). Longer or more is refused with a
            400, never cut. Each call uses the lines written in the caller's
            script (Hindi lines on a Hindi call, English on an English one).
            Words of an Indian language typed in Roman letters are converted to
            that language's script when saved. `null` or `[]` goes back to the
            built-in fillers in the caller's language.
          example:
            - One moment, let me check.
            - Just a second.
        thinkingDelayMs:
          type:
            - integer
            - 'null'
          minimum: 200
          maximum: 5000
          default: 900
          description: >-
            Milliseconds of quiet before the filler is said, 200 to 5000. `null`
            goes back to 900.
        thinkingRepeatMs:
          type:
            - integer
            - 'null'
          minimum: 1000
          maximum: 10000
          default: 2500
          description: >-
            Milliseconds after one filler before another may be said (and how
            often a long-running action is covered again), 1000 to 10000. `null`
            goes back to 2500.
        thinkingAtTurnEnd:
          type: boolean
          default: false
          description: >-
            Always acknowledge ("Okay.") the moment the caller stops, before
            every reply, instead of only when a reply is slow. Suits a slow
            model; on a quick one it is a syllable in front of everything.
        turnDetection:
          type:
            - string
            - 'null'
          enum:
            - smart
            - timer
            - ear
            - null
          description: >-
            How the agent decides the caller has finished speaking. `smart`: a
            model predicts whether the sentence is finished, so a caller who
            pauses to think is not cut off, but replies start later;
            `turnSilenceSeconds` is then a ceiling on how long it keeps waiting
            (0.6 s unless set). `timer`: a stretch of silence ends the turn,
            which is faster but cuts off people who pause mid-sentence;
            `turnSilenceSeconds` is that silence (0.25 s unless set). `ear`:
            real-time speech recognition decides when the caller has finished,
            and can stop the agent while the caller is still speaking; the agent
            uses `timer` on a line where real-time recognition is not available.
            `null` follows the platform's own setting (the Voice page shows
            which). Anything else is a 400.
        turnSilenceSeconds:
          type:
            - number
            - 'null'
          minimum: 0.2
          maximum: 3
          description: >-
            Seconds of quiet, 0.2 to 3. With `turnDetection` `timer` it is the
            silence that ends the caller's turn (0.25 s unless set); with
            `smart` it is a ceiling on how long the model may keep waiting (0.6
            s unless set). `null` goes back to the default. Shorter answers
            sooner and cuts slow speakers off more often.
        interruptWords:
          type:
            - integer
            - 'null'
          minimum: 1
          maximum: 6
          default: 3
          description: >-
            How many words a caller must say to cut the agent off while it is
            speaking, 1 to 6. Short acknowledgements ("okay", "haan") under this
            never interrupt. `null` goes back to 3.
        neverInterrupt:
          type: boolean
          default: false
          description: >-
            The agent can never be cut off, on any line, at any length — for a
            disclosure or a price read out in full. What the caller says
            meanwhile is handled by `holdShortSpeech`.
        holdShortSpeech:
          type: boolean
          default: true
          description: >-
            Keep words the caller says over the agent (too few to interrupt) and
            answer them when it stops. `false` discards them; if that was all
            the caller said, the agent finishes and waits.
        greetingUninterruptible:
          type: boolean
          default: false
          description: >-
            Let the greeting finish on phone calls even if the caller talks over
            it (callers often say "hello" on pickup). What they said is kept and
            answered next.
        ambience:
          type:
            - string
            - 'null'
          enum:
            - office
            - office-quiet
            - null
          default: null
          description: >-
            A background sound under the call: `office`, `office-quiet`, or
            `null` for none.
        ambienceVolume:
          type:
            - number
            - 'null'
          minimum: 0.05
          maximum: 1
          default: 0.15
          description: >-
            The background sound's volume, 0.05 to 1, with at most two decimal
            places (more is refused with a 400). `null` goes back to 0.15.
        speakingSpeed:
          type:
            - number
            - 'null'
          minimum: 0.7
          maximum: 1.3
          default: 1
          description: >-
            How fast the agent talks, as a multiple of the voice's own pace: 0.9
            is a little slower, 1.1 a little faster (the console's slider moves
            in steps of 0.05). Most Standard and Premium voices follow it;
            Studio voices, cloned voices and voices from your own voice account
            keep their own pace. `null` (or 1) is the voice's own pace.
        backchannelDetection:
          type: boolean
          default: true
          description: >-
            Ear mode only. Tell a caller's backchannel ("haan ji", "okay",
            "mm-hmm") from a real interruption while the agent is talking. Off:
            only `interruptWords` decides.
        backchannelWords:
          type:
            - array
            - 'null'
          items:
            type: string
            minLength: 1
            maxLength: 40
          maxItems: 30
          description: >-
            Ear mode only. Caller backchannel words that always mean "I am
            listening", on top of what the agent recognises. `null` or `[]` is
            the agent's own judgement alone.
        acknowledgements:
          type: boolean
          default: true
          description: >-
            Ear mode only. The agent speaks a short backchannel /
            acknowledgement when the caller pauses mid-explanation. Off: it
            waits silently.
        acknowledgementWords:
          type:
            - array
            - 'null'
          items:
            type: string
            minLength: 1
            maxLength: 40
          maxItems: 30
          description: >-
            Ear mode only. The agent's backchannel phrases, said in turn. `null`
            or `[]` is a short word in the caller's own language.
        endCallOnFinish:
          type: boolean
          description: >-
            Release the line when the agent ends the conversation. With it off,
            the call stays open until the caller hangs up and you are charged
            for every minute. Agents created in the console or by this API start
            with it off; an agent made earlier that never had it saved still
            reads as true.
        nudgeAfterSeconds:
          type:
            - integer
            - 'null'
          minimum: 5
          maximum: 180
          default: null
          description: >-
            Seconds of caller silence before the agent asks whether they are
            still there, 5 to 180. `null` never asks.
        nudges:
          type:
            - integer
            - 'null'
          minimum: 1
          maximum: 5
          default: 1
          description: >-
            How many times it asks before giving up, 1 to 5; reset whenever the
            caller speaks. `null` goes back to 1.
        nudgePhrase:
          type:
            - string
            - 'null'
          maxLength: 120
          description: >-
            What it asks, 120 characters or fewer (longer is a 400). `null` or
            blank asks "Are you still there?" in the caller's language.
        endAfterSilenceSeconds:
          type:
            - integer
            - 'null'
          minimum: 5
          maximum: 180
          default: null
          description: >-
            Seconds of caller silence after which the call ends, 5 to 180, or
            `null`. When the agent also asks (`nudgeAfterSeconds`), this is
            raised to at least `nudgeAfterSeconds × (nudges + 1)` so every
            question gets an answer window; with asking on and this null, the
            call ends when the last question goes unanswered.
        endPhrases:
          type:
            - array
            - 'null'
          maxItems: 12
          items:
            type: string
            minLength: 2
            maxLength: 60
          description: >-
            Phrases that end the call when the caller says them: up to 12, each
            2 to 60 characters after trimming, and still at least 2 once
            punctuation is removed (a phrase such as `!!` is refused with a 400
            that names it). Matched case-insensitively anywhere in what the
            caller says, in any language — a short word also matches inside
            longer ones. Stored lower-case with punctuation removed; duplicates
            are dropped. `null` or `[]` clears them.
          example:
            - bye
            - that is all
        callInstructions:
          type:
            - string
            - 'null'
          maxLength: 4000
          description: >-
            How the agent should speak on calls (the console's call instructions
            box), 4000 characters or fewer, separate from the agent's
            `instructions` limit. It REPLACES the built-in call rules and is
            added after the agent's instructions in the call prompt. Longer is
            refused with a 400, never cut. `null` or blank goes back to the
            built-in rules.
      example:
        voice: priya
        summariseCalls: true
        maxCallSeconds: 300
        pastConversations: quiet
        thinkingLines:
          - One moment, let me check.
        interruptWords: 2
        nudgeAfterSeconds: 10
        nudges: 2
        endPhrases:
          - bye
    AgentCollectFieldInput:
      type: object
      description: >-
        One detail to fill in after every call — the same shape as a call's
        `extract`.
      required:
        - name
      properties:
        name:
          type: string
          pattern: ^[A-Za-z][A-Za-z0-9_]{0,59}$
          description: >-
            Letters, digits and underscores, starting with a letter, up to 60
            characters. Unique, ignoring case.
        type:
          type: string
          enum:
            - text
            - number
            - integer
            - boolean
            - date
          default: text
          description: The value's type.
        description:
          type: string
          maxLength: 200
          description: What to put in it, as the model reads it.
        choices:
          type: array
          maxItems: 30
          items:
            type: string
            maxLength: 60
          description: Values a `text` field must be one of. Only for `text`.
      example:
        name: interest
        type: text
        description: How keen they sounded
        choices:
          - Hot
          - Warm
          - Cold
    AgentEscalation:
      type: object
      description: When the agent hands the conversation to a person on your team.
      required:
        - onNoAnswer
        - onRequest
      properties:
        onNoAnswer:
          type: boolean
          description: Hand over when it cannot answer.
        onRequest:
          type: boolean
          description: Hand over when the customer asks for a person.
    AgentStep:
      type: object
      description: One step of the conversation script.
      required:
        - title
        - detail
        - branches
        - collect
      properties:
        title:
          type: string
          description: What the step is for, up to 80 characters.
        detail:
          type: string
          description: What the agent should do here, up to 600 characters.
        branches:
          type: array
          description: Conditions within the step, as written. Empty when it has none.
          items:
            type: object
            required:
              - when
              - action
            properties:
              when:
                type: string
                description: The condition.
              action:
                type: string
                description: What to do when it holds.
        collect:
          type: array
          items:
            type: string
          description: What must be in hand before the step is done. Empty when nothing is.
    AgentWidget:
      type: object
      description: The website chat widget's look.
      required:
        - theme
        - accent
        - height
        - welcomeScreen
        - welcomeCollectLeads
      properties:
        theme:
          type: string
          enum:
            - classic
            - modern
          description: The widget's design.
        accent:
          type:
            - string
            - 'null'
          description: The accent colour as `#rrggbb`, or null for the default.
        height:
          type: integer
          minimum: 420
          maximum: 900
          description: The open widget's height in pixels.
        welcomeScreen:
          type: boolean
          description: Whether the widget opens on a welcome screen before the chat.
        welcomeCollectLeads:
          type: boolean
          description: Whether the welcome screen asks for the visitor's details.
    AgentVoice:
      type: object
      description: How the agent handles calls.
      required:
        - answersCalls
        - surfaces
        - voice
        - phoneNumber
        - language
        - summariseCalls
        - detectMachines
        - recordCalls
        - recordDoNotCall
        - maxCallSeconds
        - ringSeconds
        - pastConversations
        - unavailableMessage
        - unavailableMessageNote
        - callStartUrl
        - thinking
        - thinkingLines
        - thinkingDelayMs
        - thinkingRepeatMs
        - thinkingAtTurnEnd
        - turnDetection
        - turnSilenceSeconds
        - interruptWords
        - neverInterrupt
        - holdShortSpeech
        - greetingUninterruptible
        - ambience
        - ambienceVolume
        - speakingSpeed
        - backchannelDetection
        - backchannelWords
        - acknowledgements
        - acknowledgementWords
        - endCallOnFinish
        - nudgeAfterSeconds
        - nudges
        - nudgePhrase
        - endAfterSilenceSeconds
        - endPhrases
        - callInstructions
      properties:
        answersCalls:
          type: boolean
          description: Whether the agent takes calls at all.
        surfaces:
          type: array
          items:
            type: string
            enum:
              - phone
              - web
              - whatsapp
          description: >-
            Where it answers calls: a phone number, the call button on your
            website, WhatsApp calls. A new agent starts with `["web",
            "whatsapp"]`, and `phone` is added when a number is attached. Set it
            with `voice.surfaces`.
        voice:
          type:
            - string
            - 'null'
          description: The voice id from List Voices it speaks with.
        phoneNumber:
          type:
            - string
            - 'null'
          description: The number it answers on, or null. Read-only.
        language:
          type:
            - string
            - 'null'
          description: The language for calls, or null to follow the agent's `language`.
        summariseCalls:
          type: boolean
          description: Whether a summary is written after every call.
        detectMachines:
          type: boolean
          description: Whether it hangs up on an answering machine.
        recordCalls:
          type: boolean
          description: Whether calls are recorded.
        recordDoNotCall:
          type: boolean
          description: >-
            Whether the agent can add a caller to your do-not-call list when
            they ask not to be called again. True unless switched off.
        maxCallSeconds:
          type:
            - integer
            - 'null'
          minimum: 60
          maximum: 1200
          description: >-
            The longest a call may run, in seconds; null for the default ceiling
            of 20 minutes.
        ringSeconds:
          type: integer
          minimum: 10
          maximum: 60
          description: >-
            How long a call the agent places rings before it is given up; 30
            unless set. A call nobody answers in that time ends as `no_answer`.
        pastConversations:
          type: string
          enum:
            - fresh
            - quiet
            - recap
          description: >-
            What a call does with earlier conversations: `quiet` uses them
            without mentioning it, `recap` opens by recapping them, `fresh` uses
            nothing from before.
        unavailableMessage:
          type:
            - string
            - 'null'
          description: >-
            What a caller hears when this agent's line is switched off, or null
            for the standard sentence.
        unavailableMessageNote:
          type:
            - string
            - 'null'
          description: >-
            Set when the saved message will not always be spoken as written: a
            message is read aloud only on Plivo numbers (English, or English in
            Roman letters) and Twilio numbers (English and Hindi), and in no
            other script — callers then hear the standard sentence. Numbers with
            other providers, and WhatsApp calling, never speak a message; that
            is not flagged here. The message itself is kept. Null when it is
            read as written, or there is no message.
        callStartUrl:
          type:
            - string
            - 'null'
          format: uri
          description: >-
            Where an inbound call asks your system who is calling before the
            agent answers, or null. See `callStartUrl` on the input for the
            request and the answer.
        callStartSecret:
          type: string
          description: >-
            The secret that signs call-start lookups. Present ONLY on the
            response to the request that set a new `callStartUrl` — store it
            now; it is never shown again. Setting a different address creates a
            new one.
        thinking:
          type: boolean
          description: Whether it says a short filler while a reply is slow. Default true.
        thinkingLines:
          type: array
          items:
            type: string
          description: >-
            Your own filler lines. Empty means the built-in ones, in the
            caller's language.
        thinkingDelayMs:
          type: integer
          description: Milliseconds of quiet before a filler. 900 unless set.
        thinkingRepeatMs:
          type: integer
          description: Milliseconds before another filler may follow. 2500 unless set.
        thinkingAtTurnEnd:
          type: boolean
          description: Whether it acknowledges before every reply. Default false.
        turnDetection:
          type:
            - string
            - 'null'
          enum:
            - smart
            - timer
            - ear
            - null
          description: >-
            How the agent decides the caller has finished speaking: `smart`,
            `timer` or `ear`, or null when it follows the platform's own setting
            (the Voice page shows which). Reads null until you choose one.
        turnSilenceSeconds:
          type:
            - number
            - 'null'
          description: >-
            Seconds of quiet that end the caller's turn, or null for the default
            (0.25 s on most lines). In `smart` it is a ceiling on how long the
            model may keep waiting (0.6 s when null). Reads null until you set a
            number.
        interruptWords:
          type: integer
          description: >-
            Words a caller must say to cut the agent off mid-sentence. 3 unless
            set.
        neverInterrupt:
          type: boolean
          description: Whether the agent can never be cut off. Default false.
        holdShortSpeech:
          type: boolean
          description: >-
            Whether words too short to cut in are kept and answered when it
            stops. Default true.
        greetingUninterruptible:
          type: boolean
          description: Whether the greeting plays to the end on phone calls. Default false.
        ambience:
          type:
            - string
            - 'null'
          enum:
            - office
            - office-quiet
            - null
          description: A background sound under the call, or null for none.
        ambienceVolume:
          type: number
          description: The background sound's volume. 0.15 unless set.
        speakingSpeed:
          type: number
          description: >-
            How fast the agent talks, as a multiple of the voice's own pace. 1
            unless set; 0.9 is a little slower.
        backchannelDetection:
          type: boolean
          description: >-
            Ear mode only. Whether the agent tells a caller's backchannel ("haan
            ji", "okay", "mm-hmm") from a real interruption while it is talking.
            On unless set to false.
        backchannelWords:
          type: array
          items:
            type: string
          description: >-
            Ear mode only. Caller backchannel words that always mean "I am
            listening" for this agent, on top of what the agent recognises.
            Empty is the agent's own judgement alone.
        acknowledgements:
          type: boolean
          description: >-
            Ear mode only. Whether the agent speaks a short backchannel /
            acknowledgement while the caller pauses mid-explanation. On unless
            set to false; it is not part of the conversation record.
        acknowledgementWords:
          type: array
          items:
            type: string
          description: >-
            Ear mode only. The agent's backchannel phrases, said in turn. Empty
            is a short word in the caller's own language.
        endCallOnFinish:
          type: boolean
          description: >-
            Whether the line is released when the agent ends the conversation. A
            new agent starts with it off; an agent made earlier that never had
            it saved reads as true.
        nudgeAfterSeconds:
          type:
            - integer
            - 'null'
          description: >-
            Seconds of silence before it asks whether the caller is still there,
            or null to never ask.
        nudges:
          type: integer
          description: How many times it asks. 1 unless set.
        nudgePhrase:
          type:
            - string
            - 'null'
          description: >-
            What it asks, or null for the built-in question in the caller's
            language.
        endAfterSilenceSeconds:
          type:
            - integer
            - 'null'
          description: >-
            Seconds of silence after which the call ends, or null, as you set
            it. On a call the hang-up is never earlier than the last question
            allows (`nudgeAfterSeconds × (nudges + 1)`), so a call can run
            longer than this number says.
        endPhrases:
          type: array
          items:
            type: string
          description: >-
            Phrases that end the call when the caller says them, stored
            lower-case without punctuation.
        callInstructions:
          type:
            - string
            - 'null'
          description: How it should speak on calls, or null for the built-in call rules.
    AgentCollectField:
      type: object
      description: One detail the agent fills in after every call.
      required:
        - name
        - type
        - description
        - choices
      properties:
        name:
          type: string
          description: The field's key in each call's results.
        type:
          type: string
          enum:
            - text
            - number
            - integer
            - boolean
            - date
          description: The value's type.
        description:
          type:
            - string
            - 'null'
          description: What to put in it, as the model reads it.
        choices:
          type:
            - array
            - 'null'
          items:
            type: string
          description: The values a text field must be one of, or null.
  responses:
    Unauthorized:
      description: >-
        The key is missing, wrong or revoked. The answer is always the same,
        whichever it is.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: Unauthorized
            code: unauthorized
    Forbidden:
      description: >-
        The key's access level (read-only or build) does not allow this request,
        the plan does not include it, or a customer's key named another
        workspace in `Thinnest-Workspace`. `code` says which: `key_scope_read`,
        `key_scope_build`, `workspace_header_forbidden`, or `forbidden`.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          examples:
            readOnlyKey:
              summary: A read-only key tried to change something
              value:
                error: >-
                  This API key is read-only. Use a build or full key to change
                  anything.
                code: key_scope_read
            buildKey:
              summary: >-
                A build key tried to message customers, send codes or place
                calls
              value:
                error: >-
                  This API key is a build key: it can set up agents, actions,
                  contacts and webhooks, but not message customers, send codes
                  or place calls. Use a full key for that.
                code: key_scope_build
            customerKey:
              summary: A customer's key named another workspace
              value:
                error: >-
                  This key belongs to one customer workspace and cannot act as
                  another.
                code: workspace_header_forbidden
    WorkspaceDeleted:
      description: >-
        The customer named in `Thinnest-Workspace` was deleted. `POST
        /customers/{id}/restore` brings it back until its erase date.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: >-
              This workspace was deleted on 2026-10-06 and is erased on
              2026-11-05. POST /v1/customers/{id}/restore brings it back until
              then.
            code: workspace_deleted
    TooManyRequests:
      description: >-
        Over a per-minute limit. Wait for `Retry-After` seconds. `code` and
        `limit` say which limit: `rate_limit_resources` (240 requests a minute
        for the workspace), `rate_limit_family` (2,400 across a developer's
        customers), `rate_limit_calls`, `rate_limit_messages`,
        `rate_limit_codes`, `rate_limit_code_recipient`, `concurrent_calls` or
        `number_daily_limit`.
      headers:
        Retry-After:
          schema:
            type: integer
          description: Seconds to wait.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: Over 240 requests a minute. Slow down and retry.
            code: rate_limit_resources
            limit:
              name: resources
              perMinute: 240
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      description: >-
        Your API key (`ta_live_…`) from **Settings → API keys**, sent as
        `Authorization: Bearer <key>`. Keep it on a server: it can message every
        customer you have. A key is full, build or read-only; a request its
        level does not allow is refused with `403`.

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.