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
      Run your agents on your own speech-to-text, LLM and voice accounts and pay
      a flat platform fee instead of our usage rates: ₹0.02 a chat reply and ₹1
      a call minute, all-in. It is all three keys or none, and there is no
      fallback to our providers when one of your keys fails.
  - name: Webhooks
    description: >-
      Endpoints an agent's events are sent to as they happen — a CRM, a sheet,
      Slack, Zapier, or a helpdesk email address. Each delivery is a signed JSON
      `POST` of `{ "event", "sentAt", "data" }` with `x-thinnest-signature:
      sha256=<hex HMAC-SHA256 of the raw body under the endpoint's signing
      secret>`; one attempt per event, and an endpoint that fails five times in
      a row is switched off until you switch it back on.


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
      it collected, the transcript and a recording link (the same shape as Get
      Call). |

      | `campaign.finished` | Every person on a broadcast or a calling campaign
      has been reached, or given up on. |
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
                limit: 200
        '400':
          description: >-
            No `purpose`, a purpose of 300 characters or more, `calls` missing,
            empty, over 200 or holding a non-object, or several phone agents and
            no `agent`.
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
        workspace.
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
              maxLength: 299
              description: Said aloud first on every call. Under 300 characters.
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
      properties:
        error:
          type: string
          description: What went wrong, in a sentence you can show a person.
      example:
        error: That agent was not found.
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
            (`2026-10-07T10:00:00+05:30`). Up to 30 days ahead; queued, then
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
      description: The key is missing, wrong or revoked.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: 'Send a valid API key as `Authorization: Bearer <key>`.'
    Forbidden:
      description: >-
        The key's access level (read-only or build) does not allow this request,
        or the plan does not include it.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: >-
              This API key is read-only: it can read everything but change
              nothing.
    TooManyRequests:
      description: Over the per-minute limit. Wait for `Retry-After` seconds.
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