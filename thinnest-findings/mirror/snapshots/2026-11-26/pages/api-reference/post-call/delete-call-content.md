> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Call Content

> Deletes ONE call's recording and transcript, and keeps its billing record. Gone: the recording (ours, the phone provider's copy of a call on a number we rent, and any copy made for model training), this call's own turns in its conversation (other calls and chats with the same person stay), its summary, its collected fields, and the summary handed on with a warm hand-off. Kept: the call itself — when it happened, who it was with, how long it lasted, what it cost and `billing`. Afterwards Get Call answers with `recording: null`, an empty `transcript`, `contentDeleted: true` and `contentDeletedAt`. A recording that cannot be deleted at that moment is queued and retried every night until it is gone, and counted in `recordingsPending`. For a call you placed that was retried, every attempt's content goes. This cannot be undone.

This is not Cancel Call: `DELETE /calls/{id}` still calls a call off. Safe to repeat — again answers 200 with the first deletion's time. Needs a **full** key; a developer reaches a customer's call with `Thinnest-Workspace`.



## OpenAPI

````yaml /api-reference/openapi.json delete /calls/{id}/content
openapi: 3.1.0
info:
  title: ThinnestAI API
  version: 1.0.0
  description: >-
    Build voice and WhatsApp agents, place calls, message customers and run a
    platform of your own customers on one API.
servers:
  - url: https://app.thinnest.ai/api/v1
    description: Every workspace, in every country
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
      Premium or Studio — whatever model your key runs, with no model limit;
      chat replies are billed at the same flat own-keys fee as under all three
      keys. There is no fallback to our providers when one of your keys fails.
      The switch and the default `scope` are per workspace, and each agent
      follows them by default. Each agent can choose for itself (Create Agent,
      Update Agent `byok`): `null` follows the workspace, `"off"` runs that one
      agent on our voices and models at our normal pricing — chat replies billed
      normally, the voice-only model limit not applied — and a scope (`all`,
      `voice`, `llm` or `llm_voice`) runs it on that scope's keys, so one
      workspace with an LLM key and a voice key can have one agent on `llm` and
      another on `llm_voice`. A scope is refused (409, naming the missing key)
      unless you hold verified keys for it, and a key an agent's scope needs
      cannot be removed while BYOK is on. If a key is gone when a call starts,
      the agent falls back to the workspace's scope, never fails the call. A
      call is priced and run on one stack: the agent's setting is read once when
      the call or reply starts.
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
      it collected, how it went and what comes next (`insights`, when the
      agent's Call insights is on), the transcript, a recording link and what
      the call cost (`costMicro`, `currency`) — the same shape as Get Call. |

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
      `answerMs` to the first word of the actual answer, `firstTokenMs` our side
      of it — each median, p90 and max in milliseconds), long silences,
      interruptions, the turns that looked something up in the agent's knowledge
      (`knowledgeTurns`), and the turns the agent apologised for (`modelErrors`)
      or a backup model answered (`rescues`). It is null for a call that was not
      measured, and on `call.completed` when the call ended before its figures
      arrived — `call.analysed` and Get Call have them by then.
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
  - name: Workflows
    description: >-
      Journeys run once per contact: calls, WhatsApp and SMS, waits, checks and
      AI decisions, built on the Workflows page. Start one for a contact from
      your own system.
paths:
  /calls/{id}/content:
    delete:
      tags:
        - Post-call
      summary: Delete Call Content
      description: >-
        Deletes ONE call's recording and transcript, and keeps its billing
        record. Gone: the recording (ours, the phone provider's copy of a call
        on a number we rent, and any copy made for model training), this call's
        own turns in its conversation (other calls and chats with the same
        person stay), its summary, its collected fields, and the summary handed
        on with a warm hand-off. Kept: the call itself — when it happened, who
        it was with, how long it lasted, what it cost and `billing`. Afterwards
        Get Call answers with `recording: null`, an empty `transcript`,
        `contentDeleted: true` and `contentDeletedAt`. A recording that cannot
        be deleted at that moment is queued and retried every night until it is
        gone, and counted in `recordingsPending`. For a call you placed that was
        retried, every attempt's content goes. This cannot be undone.


        This is not Cancel Call: `DELETE /calls/{id}` still calls a call off.
        Safe to repeat — again answers 200 with the first deletion's time. Needs
        a **full** key; a developer reaches a customer's call with
        `Thinnest-Workspace`.
      operationId: deleteCallContent
      parameters:
        - $ref: '#/components/parameters/CallIdParam'
        - $ref: '#/components/parameters/Workspace'
      responses:
        '200':
          description: The content is deleted. `call` is Get Call's answer now.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CallContentDeleted'
              example:
                contentDeleted: true
                contentDeletedAt: '2026-10-15T09:12:40.118Z'
                recordingsPending: 0
                call: null
        '400':
          $ref: '#/components/responses/WorkspaceHeaderNotDeveloper'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          description: The key is not a full key.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  Deleting a call's recording and transcript needs a full API
                  key.
        '404':
          description: No call with that id in this workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: No call with that id.
        '409':
          description: >-
            The call is still going on, or it was booked and has not rung
            (cancel it with Cancel Call instead).
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  That call is still going on. Delete its content once it has
                  ended.
        '410':
          $ref: '#/components/responses/WorkspaceDeleted'
        '429':
          $ref: '#/components/responses/TooManyRequests'
        '503':
          description: >-
            Something could not be deleted just now. Nothing is lost by trying
            again.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  Could not delete that call's content just now. Nothing is lost
                  by trying again.
components:
  parameters:
    CallIdParam:
      name: id
      in: path
      required: true
      description: >-
        The call's `id` as Place Call or List Calls gave it: `out_…` or `sch_…`
        for a call you placed, the call reference for any other.
      schema:
        type: string
        example: out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60
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
    CallContentDeleted:
      type: object
      required:
        - contentDeleted
        - contentDeletedAt
        - recordingsPending
        - call
      properties:
        contentDeleted:
          type: boolean
          const: true
        contentDeletedAt:
          type: string
          format: date-time
          description: When the content was first deleted — the same on every repeat.
        recordingsPending:
          type: integer
          description: >-
            Recording files that could not be deleted at that moment and are
            retried every night until they are gone.
        call:
          description: The call as Get Call now answers.
          oneOf:
            - $ref: '#/components/schemas/CallReport'
            - type: 'null'
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
    CallReport:
      description: One call and what it learned — the same object `call.analysed` delivers.
      allOf:
        - $ref: '#/components/schemas/CallSummary'
        - type: object
          required:
            - insights
            - transcript
            - recording
            - retryScheduledFor
            - costMicro
            - currency
            - quality
            - usage
          properties:
            insights:
              $ref: '#/components/schemas/CallInsights'
            transcript:
              type: array
              items:
                $ref: '#/components/schemas/CallTurn'
              description: This call's spoken turns, oldest first.
            recording:
              type:
                - object
                - 'null'
              description: >-
                A signed link to the audio that needs no key — Get Recording By
                Signed Link. Null when the call was not recorded.
              required:
                - url
                - expiresAt
                - ready
              properties:
                url:
                  type: string
                  format: uri
                  description: The signed link.
                expiresAt:
                  type: string
                  format: date-time
                  description: When the link, and the recording, go.
                ready:
                  type: boolean
                  description: False while the audio has not landed yet.
            retryScheduledFor:
              type:
                - string
                - 'null'
              format: date-time
              description: >-
                When the next try will ring, if this one did not reach them and
                another is queued.
            costMicro:
              type:
                - integer
                - 'null'
              description: >-
                What this call cost the workspace, in millionths of `currency`
                (6370000 is 6.37) — the figure `GET /usage/calls` gives, at a
                white-label reseller's price for its clients. Null until the
                call is settled. Settlement runs before `call.analysed` is sent,
                so the webhook normally carries it, but it is null there too
                when the call has not settled; read Get Call later for the
                figure.
            currency:
              type:
                - string
                - 'null'
              enum:
                - INR
                - USD
                - null
              description: >-
                The currency `costMicro` is in — the workspace's. Null only for
                a booked call that has not rung.
            quality:
              $ref: '#/components/schemas/CallQuality'
            usage:
              $ref: '#/components/schemas/CallUsage'
    CallSummary:
      type: object
      description: A call, without its transcript and recording.
      required:
        - id
        - callRef
        - reference
        - metadata
        - attempt
        - status
        - direction
        - phone
        - from
        - to
        - agent
        - scheduledFor
        - startedAt
        - answeredAt
        - endedAt
        - seconds
        - hangup
        - variables
        - summary
        - fields
        - analysedAt
        - handedTo
        - forwardedTo
        - contentDeleted
        - contentDeletedAt
        - billing
        - error
      properties:
        billing:
          $ref: '#/components/schemas/CallBilling'
        id:
          type: string
          description: >-
            The id to open it by: `out_…` / `sch_…` for a call you placed, the
            call reference otherwise.
        callRef:
          type:
            - string
            - 'null'
          description: >-
            The reference of the attempt that actually rang. Null on a call that
            has not rung.
        reference:
          type:
            - string
            - 'null'
          description: Your `reference` from Place Call.
        metadata:
          type:
            - object
            - 'null'
          additionalProperties:
            type:
              - string
              - number
              - boolean
              - 'null'
          description: Your `metadata` from Place Call, untouched.
        attempt:
          type: integer
          minimum: 1
          description: 1 for the first try, 2 for the first retry.
        status:
          type: string
          enum:
            - scheduled
            - ringing
            - connected
            - completed
            - missed
            - failed
            - cancelled
          description: >-
            Where the call is. `scheduled` and `cancelled` only appear on calls
            you placed for later.
        direction:
          type: string
          enum:
            - inbound
            - outbound
          description: Who rang whom.
        phone:
          type:
            - string
            - 'null'
          description: The customer's number.
        from:
          type:
            - string
            - 'null'
          description: >-
            Your number the call rang from. Null until it rings, unless the
            request chose one, and always null on a call that came in.
        to:
          type:
            - string
            - 'null'
          description: >-
            Your number a call that came in was dialled on, in international
            format (`+918045678901`), so a workspace with several numbers can
            tell which line the caller rang. Null on a call you placed (`phone`
            is who you rang, `from` the number it rang from) and on a call that
            came in before this was kept.
        agent:
          $ref: '#/components/schemas/CallAgentRef'
        scheduledFor:
          type:
            - string
            - 'null'
          format: date-time
          description: When a booked call will ring. Null once it has.
        startedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it started ringing.
        answeredAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it was picked up.
        endedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it ended.
        seconds:
          type: integer
          minimum: 0
          description: >-
            How long it lasted. On a call forwarded to a phone (`forwardedTo`)
            this is how long the caller was connected - answer to hang-up - even
            when nothing was billed (a number you brought bills nothing for a
            forward). 0 for a forward nobody picked up (`status` `missed`).
        hangup:
          type:
            - string
            - 'null'
          enum:
            - answered
            - no_answer
            - busy
            - rejected
            - unreachable
            - cancelled
            - voicemail
            - before_agent
            - failed
            - not_placed
            - null
          description: >-
            Why it ended. Null while live; `not_placed` for a booked call that
            never rang.
        variables:
          type: object
          additionalProperties:
            type: string
          description: The `{{name}}` values the call used.
        summary:
          type:
            - string
            - 'null'
          description: Two or three sentences about the call, when summarised.
        fields:
          type: object
          additionalProperties: true
          description: >-
            The collected details, keyed by field name. Empty when nothing was
            said.
        analysedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When the summary and fields were written. Null means they may still
            arrive.
        handedTo:
          type: array
          description: >-
            Every agent the call was handed to mid-call, oldest first (set on
            the agent's Actions page, under Hand calls to another agent). Empty
            when it stayed with `agent`, which is always the agent the call was
            placed or answered as. A hand-off to another agent is not a
            hand-over to a person: it sends no `conversation.escalated`.
          items:
            type: object
            required:
              - agent
              - from
              - at
              - mode
              - summary
            properties:
              agent:
                $ref: '#/components/schemas/CallAgentRef'
              from:
                $ref: '#/components/schemas/CallAgentRef'
              at:
                type: string
                format: date-time
                description: When it was handed over.
              mode:
                type: string
                enum:
                  - warm
                  - cold
                description: >-
                  How it was handed over. `warm`: the agent got a summary and
                  the conversation. `cold`: it started without the conversation
                  and greeted the caller afresh. Calls handed over before warm
                  and cold existed read `warm`.
              summary:
                type:
                  - string
                  - 'null'
                description: >-
                  On a warm hand-off, the summary the next agent was given:
                  written by the previous agent, or built from the caller's last
                  words when it wrote none. Up to 300 characters. Null on a cold
                  hand-off.
        forwardedTo:
          type:
            - string
            - 'null'
          description: >-
            The phone this call was forwarded to, when the number forwards every
            call (`forwardTo` on the phone number) and no agent answered it.
            Null on every other call. A forwarded call has no transcript,
            summary or fields.
        contentDeleted:
          type: boolean
          description: >-
            True once the call's recording and transcript were deleted — by
            Delete Call Content, or by the workspace's `callRetentionDays`. The
            summary, fields, transcript and recording are then empty; when it
            happened, how long it lasted and what it cost stay.
        contentDeletedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When its content was deleted; null while it is kept.
        error:
          type:
            - string
            - 'null'
          description: Why a booked call could not be placed, in words. Null otherwise.
    CallInsights:
      type:
        - object
        - 'null'
      description: >-
        What the call came to: how it ended, the customer's objections, why a no
        was a no, problems on the customer's side, and the next step agreed.
        Written once the call is read, before `call.analysed` is sent. Null when
        the agent's Call insights is off (Agents → the agent → Voice), for a web
        call, a call nobody spoke on, or a call whose content was deleted. Only
        what the customer actually said is noted.
      required:
        - outcome
        - noReason
        - objections
        - issues
        - nextStep
      properties:
        outcome:
          type: string
          enum:
            - converted
            - interested
            - callback
            - promise_to_pay
            - not_interested
            - no_decision
            - wrong_person
            - do_not_call
          description: >-
            How it ended. `converted`: the customer agreed to what the call was
            for (bought, booked, paid, signed up).
        noReason:
          type:
            - string
            - 'null'
          enum:
            - price
            - timing
            - trust
            - fit
            - already_has
            - other
            - null
          description: Why a no was a no; set only when `outcome` is `not_interested`.
        objections:
          type: array
          maxItems: 5
          description: Up to five, in the customer's words.
          items:
            type: object
            required:
              - text
              - kind
            properties:
              text:
                type: string
                maxLength: 120
                example: The EMI is too high
              kind:
                type: string
                enum:
                  - price
                  - timing
                  - trust
                  - fit
                  - need
                  - authority
                  - competitor
                  - other
        issues:
          type: array
          maxItems: 5
          description: >-
            Problems the customer has with your own service — a payment link
            that does not open, a double charge.
          items:
            type: object
            required:
              - text
              - kind
            properties:
              text:
                type: string
                maxLength: 120
                example: Payment link does not open
              kind:
                type: string
                enum:
                  - payment
                  - billing
                  - login
                  - delivery
                  - product
                  - other
        nextStep:
          type:
            - object
            - 'null'
          description: The next step the call settled, or null.
          required:
            - kind
            - at
            - note
            - status
            - followedUpAt
          properties:
            kind:
              type: string
              enum:
                - callback
                - promise_to_pay
                - send_info
                - visit
                - hand_to_sales
            at:
              type:
                - string
                - 'null'
              format: date-time
              description: >-
                The day (and time) agreed; a day without a time is 10:00 in the
                call's time zone. Null when the call settled no date.
            note:
              type: string
              maxLength: 300
              description: One short line, possibly empty.
            status:
              type: string
              enum:
                - open
                - done
                - replaced
              description: >-
                `open` while on the follow-up list; `done` when someone marked
                it Done on the Insights page; `replaced` when a later call with
                the same contact settled a newer next step (or none).
            followedUpAt:
              type:
                - string
                - 'null'
              format: date-time
              description: When it was marked Done or replaced; null while open.
    CallTurn:
      type: object
      required:
        - speaker
        - text
        - at
      properties:
        speaker:
          type: string
          enum:
            - customer
            - agent
            - team
          description: Who spoke — `team` is a teammate who took the conversation over.
        text:
          type: string
          description: What was said.
        at:
          type: string
          format: date-time
          description: When the turn was written down.
    CallQuality:
      type:
        - object
        - 'null'
      description: >-
        How the call went, in numbers, written once when it ends. Null for a
        call that was not measured — a call from before call quality was
        recorded, a call that never connected, or one whose voice connection
        never reported. A figure inside is null when the part of the call that
        measures it did not report.
      required:
        - turns
        - responseMs
        - answerMs
        - firstTokenMs
        - longSilences
        - longSilenceSeconds
        - longestSilenceSeconds
        - interruptions
        - knowledgeTurns
        - modelErrors
        - rescues
      properties:
        turns:
          type:
            - integer
            - 'null'
          minimum: 0
          description: >-
            Caller turns the agent answered. A turn that got no reply (an echo
            of the agent's own voice, a turn after it hung up) is not counted.
        responseMs:
          type:
            - object
            - 'null'
          description: >-
            How long the caller waited: from when they stopped speaking to the
            agent's first audio on the line. Null when it was not measured.
          required:
            - median
            - p90
            - max
          properties:
            median:
              type: integer
              minimum: 0
              description: Half the turns were faster than this, in milliseconds.
            p90:
              type: integer
              minimum: 0
              description: Nine turns in ten were at least this fast, in milliseconds.
            max:
              type: integer
              minimum: 0
              description: The slowest turn, in milliseconds.
        answerMs:
          type:
            - object
            - 'null'
          description: >-
            How long the caller waited for the first word of the ACTUAL answer:
            from when they stopped speaking to that word being heard.
            `responseMs` stops at the first sound of any kind, so a thinking
            line or an acknowledgement that plays first ends it; this does not.
            When a thinking line spoke first the answer's start is worked out
            from the audio queued behind it (the turn's `answerAudioEstimated`
            in Get Call Timeline says so). Only turns that had answer words
            count. Null when it was not measured, and on calls from before it
            was recorded.
          required:
            - median
            - p90
            - max
          properties:
            median:
              type: integer
              minimum: 0
              description: Half the turns were faster than this, in milliseconds.
            p90:
              type: integer
              minimum: 0
              description: Nine turns in ten were at least this fast, in milliseconds.
            max:
              type: integer
              minimum: 0
              description: The slowest turn, in milliseconds.
        firstTokenMs:
          type:
            - object
            - 'null'
          description: >-
            Our side of that wait: from the turn reaching the model to its first
            word. Null when it was not measured.
          required:
            - median
            - p90
            - max
          properties:
            median:
              type: integer
              minimum: 0
              description: Half the turns were faster than this, in milliseconds.
            p90:
              type: integer
              minimum: 0
              description: Nine turns in ten were at least this fast, in milliseconds.
            max:
              type: integer
              minimum: 0
              description: The slowest turn, in milliseconds.
        longSilences:
          type:
            - integer
            - 'null'
          minimum: 0
          description: Silences, on either side, at least `longSilenceSeconds` long.
        longSilenceSeconds:
          type:
            - number
            - 'null'
          description: >-
            How long a silence had to be to count: the agent's "are you still
            there?" time, or 10 seconds when it has none.
        longestSilenceSeconds:
          type:
            - number
            - 'null'
          description: The longest stretch where nobody spoke.
        interruptions:
          type:
            - integer
            - 'null'
          minimum: 0
          description: Times the caller started speaking while the agent was talking.
        knowledgeTurns:
          type:
            - integer
            - 'null'
          minimum: 0
          description: >-
            Turns where the agent looked something up in its knowledge: its own
            search, or passages handed to it up front. Null when this count was
            not available for the call.
        modelErrors:
          type:
            - integer
            - 'null'
          minimum: 0
          description: >-
            Turns where the agent could not get an answer and apologised to the
            caller instead. Null when this count was not available for the call.
        rescues:
          type:
            - integer
            - 'null'
          minimum: 0
          description: >-
            Turns where the agent's model failed and a backup model answered, so
            the caller still got a reply. Null when this count was not available
            for the call.
    CallUsage:
      type: object
      description: >-
        What the call used: the language-model tokens its replies used, whether
        the model is ours or your own key's (BYOK), and the characters sent to
        the voice. Each is null when it was not recorded: a call that never
        reached the model (a missed call, a forward, a booked call that has not
        rung). The input count is what the provider reported; where a provider
        reports none it is estimated from the prompt's length, and
        `inputTokensEstimated` says so. The call's summary and field extraction
        after it ends are not counted.
      required:
        - inputTokens
        - outputTokens
        - cachedInputTokens
        - inputTokensEstimated
        - ttsCharacters
      properties:
        inputTokens:
          type:
            - integer
            - 'null'
          description: >-
            Tokens sent to the model across the call's replies, cached ones
            included.
        outputTokens:
          type:
            - integer
            - 'null'
          description: Tokens the model wrote across the call's replies.
        cachedInputTokens:
          type:
            - integer
            - 'null'
          description: >-
            How many of `inputTokens` the provider served from its cache. Null
            when the provider reports no cache figure.
        inputTokensEstimated:
          type:
            - boolean
            - 'null'
          description: >-
            True when any reply's input count was estimated from the prompt's
            length because the provider reported none, so `inputTokens` is
            partly an estimate; false when every reply's count came from the
            provider. Null when no tokens were recorded, and for calls before 15
            October 2026.
        ttsCharacters:
          type:
            - integer
            - 'null'
          description: >-
            Characters of text sent to the voice to be spoken: every reply, the
            greeting, fillers and other fixed lines. It includes text sent
            before the caller interrupted, even if they never heard it, which is
            what a voice provider charges for, and it is counted on your own
            voice key (BYOK) too. Null when nothing was sent.
    CallBilling:
      type:
        - object
        - 'null'
      description: >-
        What the call was billed as. Null for a booked call that has not rung.


        **Carrier-only calls.** A call that ended before the agent spoke runs no
        agent (no recogniser, model or voice), so it is charged the phone
        carrier's fee only: ₹0.38 a minute in INR, charged in 30-second blocks
        (₹0.19 each; in USD at our conversion rate). `billedSeconds` is the
        length rounded up to the block. For these calls `voicePlan` and
        `ratePerMinuteMicro` still show the plan and rate the call was set up
        on, which is not what was charged: reconcile such a call by `costMicro`.


        **A call that ends at 0 seconds** is not charged at all: `billedSeconds`
        stays null. One that lasts a second is one 30-second block.


        **Forwarded calls are not carrier-only.** A call forwarded to a phone
        (`forwardedTo`) on a number rented here is billed for every second the
        caller was connected, at the rate it was admitted at: the voice plan of
        the agent attached to the number, or the Premium plan when no agent is.
        When your own keys apply (the agent's, or the workspace's when no agent
        is attached), that is the flat own-key price of the set instead
        (`voicePlan` is null), even though the forward uses none of your keys.
        On a number you brought nothing is charged: `ratePerMinuteMicro` still
        shows the rate the call was admitted at, and `billedSeconds` is null.


        **Free trial calls.** `voicePlan`, `ratePerMinuteMicro` and
        `billedSeconds` are null for a call paid from a free-plan workspace's
        trial minutes. A call in a workspace on a paid plan, a developer's own
        test calls included, is billed from its balance and carries them.
      required:
        - billedOn
        - chargedMicro
        - keys
        - voicePlan
        - ratePerMinuteMicro
        - billedSeconds
        - currency
      properties:
        billedOn:
          type: string
          enum:
            - plan
            - usage
          description: >-
            `usage` for a call on a realtime (speech-to-speech) model, OpenAI
            GPT-Live-1: it is charged at that model's own flat rate a minute
            with the phone line included, per second on web and in 30-second
            blocks on phone (`billedSeconds`), so `voicePlan` and
            `ratePerMinuteMicro` are null and `chargedMicro` is the charge.
            `plan` for every other call.
        chargedMicro:
          type:
            - integer
            - 'null'
          description: >-
            What a call billed on usage was charged, in millionths of
            `currency`, at a white-label reseller's price for its clients. Null
            on a call billed on a plan, and until a usage call has been charged.
        keys:
          type: string
          enum:
            - 'off'
            - all
            - voice
            - llm
            - llm_voice
          description: >-
            Whose keys the call ran on, as it was set up when the call started:
            `off` for ours; `all` your speech recognition, model and voice;
            `voice` your voice only; `llm` your model only; `llm_voice` your
            model and voice.
        voicePlan:
          type:
            - string
            - 'null'
          enum:
            - standard
            - premium
            - studio
            - null
          description: >-
            The voice plan the call was priced on (`off` and `llm` calls).
            `standard` appears only on calls before 23 October 2026, when
            standard voices were retired. Null for the flat own-key prices
            (`all`, `voice`, `llm_voice`), for a free trial call, and for calls
            before 15 October 2026.
        ratePerMinuteMicro:
          type:
            - integer
            - 'null'
          description: >-
            The per-minute price the call was charged at, fixed when it started,
            in millionths of `currency` (2000000 is 2.00) — at a white-label
            reseller's price for its clients. A call is charged in 30-second
            steps (a WhatsApp call by the minute) at half of this each. Null for
            a free trial call.
        billedSeconds:
          type:
            - integer
            - 'null'
          description: >-
            The seconds the charge was for: the call's length rounded up to its
            step, or to the phone carrier's block for a call that ended before
            the agent spoke (charged the carrier's fee only). Null until a
            charge was taken — a call still live, a free trial call, and calls
            settled before 15 October 2026.
        currency:
          type:
            - string
            - 'null'
          enum:
            - INR
            - USD
            - null
          description: The currency the rate is in, as `currency` on the call.
    CallAgentRef:
      type:
        - object
        - 'null'
      description: >-
        The agent on the call. Null on a call forwarded to a phone when no agent
        answered the number (`forwardedTo` is set).
      required:
        - id
        - name
      properties:
        id:
          type: string
          description: Its `ag_…` id.
        name:
          type:
            - string
            - 'null'
          description: Its name.
  responses:
    WorkspaceHeaderNotDeveloper:
      description: >-
        `Thinnest-Workspace` was sent from a workspace that is not a developer
        workspace.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: >-
              Thinnest-Workspace needs a developer workspace. Create a customer
              first with POST /v1/customers.
            code: workspace_not_developer
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