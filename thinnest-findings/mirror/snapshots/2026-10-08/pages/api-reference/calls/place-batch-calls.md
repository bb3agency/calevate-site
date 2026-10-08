> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Place Batch Calls

> Rings up to 200 people with one request. Every option Place Call takes may be set once for the batch and again on an entry, the entry winning (an entry's `variables` sit on top of the batch's); `purpose` and `agent` are the batch's. Every entry is queued and paced inside your plan's lines and balance — none rings inline — and each gets its own `sch_…` id that reports through `call.analysed` and Get Call. A bad entry is listed under `refused` and does not stop the rest. Needs a **full** key.



## OpenAPI

````yaml /api-reference/openapi.json post /calls/batch
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
      chat replies as usual, on any model. There is no fallback to our providers
      when one of your keys fails. The switch is per workspace, and each agent
      follows it by default: set an agent's `byok` to `"off"` (Create Agent,
      Update Agent) and that one agent runs on our voices and models at our
      normal pricing — chat replies billed normally, the voice-only model limit
      not applied — while your other agents stay on your keys. A call is priced
      and run on one stack: the agent's setting is read once when the call or
      reply starts.
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


      The events an endpoint can subscribe to:


      | Event | When it fires |

      |---|---|

      | `lead.captured` | The agent collected a name, email or phone from
      somebody who showed real interest. |

      | `conversation.escalated` | The agent handed a conversation to a person —
      asked for, or because it could not answer. |

      | `conversation.resolved` | A teammate marked a conversation done;
      `data.conversationId` is its `conv_…` id, as Get Conversation takes it. |

      | `call.completed` | A call the agent placed or answered ended — how it
      ended and how long it lasted, sent the moment it ends. |

      | `call.analysed` | A call's results are ready: its summary, the details
      it collected, the transcript, a recording link and what the call cost
      (`costMicro`, `currency`) — the same shape as Get Call. |

      | `campaign.finished` | Every person on a broadcast or a calling campaign
      has been reached, or given up on. |

      | `contact.opted_out` | During a call, somebody asked not to be called
      again; their number (`data.phone`) is now on the do-not-call list;
      `data.source` is `"call"`. |
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
paths:
  /calls/batch:
    post:
      tags:
        - Calls
      summary: Place Batch Calls
      description: >-
        Rings up to 200 people with one request. Every option Place Call takes
        may be set once for the batch and again on an entry, the entry winning
        (an entry's `variables` sit on top of the batch's); `purpose` and
        `agent` are the batch's. Every entry is queued and paced inside your
        plan's lines and balance — none rings inline — and each gets its own
        `sch_…` id that reports through `call.analysed` and Get Call. A bad
        entry is listed under `refused` and does not stop the rest. Needs a
        **full** key.
      operationId: placeBatchCalls
      parameters:
        - $ref: '#/components/parameters/IdempotencyKey'
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CallBatchRequest'
            example:
              agent: Skyline Sales
              purpose: >-
                I'm calling from Skyline Homes about the new tower launching at
                Baner.
              callingHours:
                start: '10:00'
                end: '19:00'
                days:
                  - mon
                  - tue
                  - wed
                  - thu
                  - fri
                  - sat
              extract:
                - name: interest
                  choices:
                    - Hot
                    - Warm
                    - Cold
              summary: true
              variables:
                project: Sky Towers
              retry:
                count: 1
              calls:
                - to: '919876543210'
                  name: Asha Rao
                  reference: LSQ-42
                  variables:
                    lead_name: Asha
                - to: +91 99200 11223
                  name: Vikram Shah
                  reference: LSQ-43
                - to: '12345'
                  reference: LSQ-44
      responses:
        '202':
          description: The entries queued and the entries refused.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CallBatchResult'
              example:
                accepted:
                  - id: sch_2d7b0e91-4f3a-4c88-9b1e-7a6c5d4e3f21
                    to: '919876543210'
                    reference: LSQ-42
                    from: null
                    status: scheduled
                    scheduledFor: '2026-10-06T05:12:44.019Z'
                  - id: sch_7e1f4a20-9c3b-4d5e-8f6a-1b2c3d4e5f60
                    to: '919920011223'
                    reference: LSQ-43
                    from: null
                    status: scheduled
                    scheduledFor: '2026-10-06T05:12:44.019Z'
                refused:
                  - to: '12345'
                    reference: LSQ-44
                    error: >-
                      That number could not be read — too short to be a phone
                      number.
                    code: invalid_number
                limit: 200
        '400':
          description: >-
            No `purpose`, a purpose over 300 characters, `calls` missing, empty,
            over 200 or holding a non-object, or several phone agents and no
            `agent`.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                purpose:
                  value:
                    error: >-
                      `purpose` is required — it is the first thing said aloud
                      on every call.
                calls:
                  value:
                    error: '`calls` may hold at most 200 entries per request.'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: '`agent` names no agent that answers the phone in this workspace.'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  No agent of that name or id answers the phone in this
                  workspace.
                code: agent_not_found
        '409':
          description: >-
            The workspace cannot place calls, no agent answers the phone, or the
            same `Idempotency-Key` is still being processed.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  This workspace cannot place calls. Its phone provider is not
                  connected.
        '410':
          $ref: '#/components/responses/WorkspaceDeleted'
        '429':
          $ref: '#/components/responses/TooManyRequests'
components:
  parameters:
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: false
      description: >-
        Any unique string. A retry with the same key within 24 hours returns the
        first request's answer instead of acting twice.
      schema:
        type: string
        maxLength: 255
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
    CallBatchRequest:
      description: >-
        Up to 200 calls with one purpose and one agent. The options below apply
        to every entry unless the entry says otherwise.
      allOf:
        - type: object
          required:
            - purpose
            - calls
          properties:
            purpose:
              type: string
              minLength: 1
              maxLength: 300
              description: Said aloud first on every call. 300 characters or fewer.
            agent:
              type: string
              description: >-
                Which agent calls — its `ag_…` id or name. Needed only when more
                than one agent answers the phone.
            calls:
              type: array
              minItems: 1
              maxItems: 200
              items:
                $ref: '#/components/schemas/CallBatchEntry'
              description: The people to ring.
            idempotencyKey:
              type: string
              description: >-
                The same as the `Idempotency-Key` header. One key covers the
                whole batch.
        - $ref: '#/components/schemas/CallOptions'
    CallBatchResult:
      type: object
      required:
        - accepted
        - refused
        - limit
      properties:
        accepted:
          type: array
          items:
            $ref: '#/components/schemas/CallBatchAccepted'
        refused:
          type: array
          items:
            $ref: '#/components/schemas/CallBatchRefused'
        limit:
          type: integer
          description: The most entries one request may hold (200).
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
            - invalid_number
            - number_required
            - number_claimed_elsewhere
            - needs_own_carrier_keys
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
    CallBatchEntry:
      description: One person to ring. Its own options win over the batch's.
      allOf:
        - type: object
          required:
            - to
          properties:
            to:
              type: string
              description: >-
                The person's number, with or without `+`. A number listed twice
                is refused the second time.
        - $ref: '#/components/schemas/CallOptions'
    CallOptions:
      type: object
      description: >-
        What Place Call accepts beyond `to`, `purpose` and `agent` — also what a
        batch may set once or per entry.
      properties:
        name:
          type: string
          maxLength: 120
          description: >-
            The lead's name. A number that is not a contact yet becomes one with
            this name; an existing contact's name is never overwritten.
        source:
          type: string
          maxLength: 120
          description: >-
            Where the lead came from, e.g. `99acres enquiry form` — recorded on
            a new contact.
        reference:
          type: string
          maxLength: 200
          description: >-
            Your own id for this lead, never interpreted. It comes back on the
            response, every report and both call webhooks.
        variables:
          type: object
          additionalProperties:
            type: string
          description: >-
            Values the agent's instructions use as `{{name}}`. Up to 20; names
            are lower-cased with spaces turned into `_`, values cut to 150
            characters.
        callingHours:
          $ref: '#/components/schemas/CallCallingHours'
        ifOutsideHours:
          type: string
          enum:
            - schedule
            - refuse
          default: schedule
          description: >-
            Outside the calling hours right now: `schedule` queues the call for
            the minute they open; `refuse` answers `409` with `nextOpening` and
            does nothing. Does not apply to a call with `scheduledAt`, nor to a
            batch (which always queues).
        extract:
          type: array
          maxItems: 30
          items:
            $ref: '#/components/schemas/AgentCollectFieldInput'
          description: >-
            The details to fill from the call, keyed back exactly as named. A
            value that does not fit its type is left out rather than sent wrong.
            Leave it out for the agent's own collected fields.
        summary:
          type: boolean
          description: >-
            `true` writes two or three sentences about the call, `false` skips
            it. Leave it out to follow the agent's own switch.
        metadata:
          type: object
          maxProperties: 20
          additionalProperties:
            type:
              - string
              - number
              - boolean
              - 'null'
          description: >-
            Your own flat data, returned exactly as sent on every report and
            webhook. Up to 20 keys of 1–60 characters, 4,000 characters
            serialised; values are strings, numbers, booleans or null — a nested
            object or list is refused.
        scheduledAt:
          type: string
          format: date-time
          description: >-
            Don't ring before this instant, written with its offset
            (`2027-03-08T10:00:00+05:30`). Up to 30 days ahead; queued, then
            rung at this time or the next opening of the calling hours after it.
            A time already past means now.
        retry:
          $ref: '#/components/schemas/CallRetry'
        from:
          type: string
          description: >-
            Which of the agent's numbers rings — its own, or one lent to it for
            calling (List Phone Numbers). Leave it out for the agent's own line.
            On an agent with several numbers, a chosen number places at most 200
            calls a day.
        overrides:
          $ref: '#/components/schemas/CallOverrides'
    CallBatchAccepted:
      type: object
      required:
        - id
        - to
        - reference
        - from
        - status
        - scheduledFor
      properties:
        id:
          type: string
          description: The call's `sch_…` id.
        to:
          type: string
          description: The number as it will be dialled.
        reference:
          type:
            - string
            - 'null'
          description: The entry's `reference`.
        from:
          type:
            - string
            - 'null'
          description: The chosen `from` number, or null for the agent's own line.
        status:
          type: string
          const: scheduled
        scheduledFor:
          type: string
          format: date-time
          description: The earliest it may ring; the queue paces calls from then on.
    CallBatchRefused:
      type: object
      required:
        - to
        - reference
        - error
      properties:
        to:
          type: string
          description: The number as sent, or as read.
        reference:
          type:
            - string
            - 'null'
          description: The entry's `reference`.
        error:
          type: string
          description: Why this entry was not queued.
        code:
          type: string
          enum:
            - invalid_number
            - opted_out
            - do_not_call
            - stop_list_unknown
            - number_never_callable
            - call_already_scheduled
          description: >-
            For the refusals a client branches on (a number that could not be
            read, an opted-out customer, the do-not-call list, hours that never
            open, a call already waiting). Absent for the others; read `error`.
    CallCallingHours:
      type: object
      description: >-
        When this person may be rung, in their own time. Leave it out for any
        day, 09:00 to 21:00.
      properties:
        start:
          type: string
          description: >-
            Opening time, `HH:MM`. No earlier than 09:00 — an earlier time is
            refused, not moved.
          default: '09:00'
          example: '10:00'
        end:
          type: string
          description: Closing time, `HH:MM`, later than `start`. No later than 21:00.
          default: '21:00'
          example: '19:00'
        days:
          type: array
          description: The weekdays calls may be placed on. Leave it out for every day.
          minItems: 1
          items:
            type: string
            enum:
              - mon
              - tue
              - wed
              - thu
              - fri
              - sat
              - sun
          example:
            - mon
            - tue
            - wed
            - thu
            - fri
            - sat
        timezone:
          type: string
          description: >-
            An IANA zone, used only for a number whose country cannot be placed;
            an Indian number is always read in India's time. Defaults to your
            workspace's zone.
          example: Asia/Kolkata
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
    CallRetry:
      type: object
      description: >-
        Try again when the person was not reached (no answer, busy, an answering
        machine, or a pick-up the agent never reached). A declined call, a dead
        number and a call somebody answered are never retried. A retry keeps the
        same `id`, rings only inside the calling hours, and is checked again
        against opt-outs and the do-not-call list.
      required:
        - count
      properties:
        count:
          type: integer
          minimum: 0
          maximum: 5
          description: Further attempts after the first. 0 means none.
        noAnswerMinutes:
          type: integer
          minimum: 5
          maximum: 1440
          default: 60
          description: >-
            Minutes to wait after a call nobody answered, or an answering
            machine took.
        busyMinutes:
          type: integer
          minimum: 5
          maximum: 1440
          default: 15
          description: Minutes to wait after an engaged line.
      example:
        count: 2
        noAnswerMinutes: 60
        busyMinutes: 15
    CallOverrides:
      type: object
      description: >-
        Changes to the agent for this call only; the agent itself is not edited.
        Any other key is refused by name.
      properties:
        voice:
          type: string
          maxLength: 100
          description: >-
            A voice id from List Voices — or, on a workspace that brings its own
            keys, a voice your own provider offers (List BYOK Voices). A premium
            voice bills this call at the premium rate.
        language:
          type: string
          description: >-
            A language the console offers, e.g. `Hindi` — what the call is heard
            and spoken in. `auto` is not accepted: leave it out for the agent's
            own behaviour.
        maxCallSeconds:
          type: integer
          minimum: 60
          maximum: 1200
          description: The longest this call may run, in seconds.
        callInstructions:
          type: string
          minLength: 1
          maxLength: 4000
          description: >-
            Replaces the agent's call instructions (the box on its Voice page)
            for this call.
      example:
        voice: priya
        language: Hindi
        maxCallSeconds: 300
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