> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# List Calls

> Every call your workspace made or took — inbound, website, WhatsApp, a campaign's or one you placed — newest first, without transcripts or recordings. Each item's `id` opens the call with Get Call. A call booked for later appears here only once it has rung; read a booked call by the `sch_…` id Place Call gave you.



## OpenAPI

````yaml /api-reference/openapi.json get /calls
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
  /calls:
    get:
      tags:
        - Calls
      summary: List Calls
      description: >-
        Every call your workspace made or took — inbound, website, WhatsApp, a
        campaign's or one you placed — newest first, without transcripts or
        recordings. Each item's `id` opens the call with Get Call. A call booked
        for later appears here only once it has rung; read a booked call by the
        `sch_…` id Place Call gave you.
      operationId: listCalls
      parameters:
        - $ref: '#/components/parameters/Limit'
        - $ref: '#/components/parameters/Cursor'
        - name: agent
          in: query
          required: false
          description: Only this agent's calls — its `ag_…` id.
          schema:
            type: string
            example: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
        - name: status
          in: query
          required: false
          description: Only calls in this state.
          schema:
            type: string
            enum:
              - ringing
              - connected
              - completed
              - missed
              - failed
            example: completed
        - name: reference
          in: query
          required: false
          description: >-
            Only calls placed with this `reference` — your CRM's own id for the
            lead. Matched exactly; up to 200 characters are read.
          schema:
            type: string
            maxLength: 200
            example: LSQ-42
        - name: since
          in: query
          required: false
          description: >-
            Only calls that started at or after this date (`2026-09-17`) or
            instant (`2026-09-17T10:00:00Z`).
          schema:
            type: string
            example: '2026-10-01'
        - name: until
          in: query
          required: false
          description: Only calls that started at or before this date or instant.
          schema:
            type: string
            example: '2026-10-06T23:59:59+05:30'
        - $ref: '#/components/parameters/Workspace'
      responses:
        '200':
          description: A page of calls.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CallList'
              example:
                items:
                  - id: out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60
                    callRef: out_9f2c1a44-6b0e-4c1d-8a7f-2e5b3c9d1f60
                    reference: LSQ-42
                    metadata:
                      deal_id: D-19
                      owner: Ravi
                    attempt: 1
                    status: completed
                    direction: outbound
                    phone: '919876543210'
                    from: '918045678901'
                    agent:
                      id: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
                      name: Skyline Sales
                    scheduledFor: null
                    startedAt: '2026-10-06T04:30:02.118Z'
                    answeredAt: '2026-10-06T04:30:09.540Z'
                    endedAt: '2026-10-06T04:33:11.902Z'
                    seconds: 182
                    hangup: answered
                    variables:
                      lead_name: Asha
                      project: Sky Towers
                    summary: >-
                      Asha is keen on a 2 BHK at Sky Towers with a budget around
                      80 lakh. She asked to visit the site on Saturday.
                    fields:
                      budget: 8000000
                      interest: Hot
                      site_visit: true
                    analysedAt: '2026-10-06T04:33:20.311Z'
                    error: null
                nextCursor: MjAyNi0xMC0wNlQwNDozMDowMi4xMThafDNiN2UxYzkw
        '400':
          description: A filter is not valid.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  `status` must be one of ringing, connected, completed, missed,
                  failed.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '429':
          $ref: '#/components/responses/TooManyRequests'
components:
  parameters:
    Limit:
      name: limit
      in: query
      required: false
      description: How many items to return, 1 to 100.
      schema:
        type: integer
        minimum: 1
        maximum: 100
        default: 25
    Cursor:
      name: cursor
      in: query
      required: false
      description: >-
        The `nextCursor` from the previous page. Leave it out for the first
        page.
      schema:
        type: string
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
    CallList:
      type: object
      required:
        - items
        - nextCursor
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/CallSummary'
        nextCursor:
          type:
            - string
            - 'null'
          description: Pass as `cursor` for the next page. Null on the last page.
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
        - error
      properties:
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
            request chose one.
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
          description: How long it lasted.
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
        error:
          type:
            - string
            - 'null'
          description: Why a booked call could not be placed, in words. Null otherwise.
    CallAgentRef:
      type:
        - object
        - 'null'
      description: The agent on the call.
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
    Unauthorized:
      description: The key is missing, wrong or revoked.
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/Error'
          example:
            error: 'Send a valid API key as `Authorization: Bearer <key>`.'
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