> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Create Campaign

> Creates a WhatsApp broadcast (`kind: "whatsapp"`) or a calling campaign (`kind: "voice"`) as a draft, with the same checks as the console's builder: WhatsApp connected and the template approved with every blank filled, or for calls an agent with a number that answers phone calls and is licensed for this kind of call. The audience is built from your contacts right away, by consent; people who asked not to be contacted are always left out. Send `launch: true` to start it at once, or `scheduledAt` to start it later; a launch that is refused (no paid plan, not enough balance) still leaves the draft and says why in `message`, and an audience of nobody is never launched. Needs a **full** key.



## OpenAPI

````yaml /api-reference/openapi.json post /campaigns
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
  /campaigns:
    post:
      tags:
        - Campaigns
      summary: Create Campaign
      description: >-
        Creates a WhatsApp broadcast (`kind: "whatsapp"`) or a calling campaign
        (`kind: "voice"`) as a draft, with the same checks as the console's
        builder: WhatsApp connected and the template approved with every blank
        filled, or for calls an agent with a number that answers phone calls and
        is licensed for this kind of call. The audience is built from your
        contacts right away, by consent; people who asked not to be contacted
        are always left out. Send `launch: true` to start it at once, or
        `scheduledAt` to start it later; a launch that is refused (no paid plan,
        not enough balance) still leaves the draft and says why in `message`,
        and an audience of nobody is never launched. Needs a **full** key.
      operationId: createCampaign
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CampaignCreate'
            examples:
              broadcast:
                summary: A WhatsApp broadcast
                value:
                  kind: whatsapp
                  name: Diwali sale — VIP customers
                  template: diwali_offer_v2
                  language: en
                  variables:
                    - position: 1
                      source: contact_name
                    - position: 2
                      source: fixed
                      value: FESTIVE20
                  tags:
                    - vip
                  launch: true
              calling:
                summary: A calling campaign
                value:
                  kind: voice
                  name: Six-month check-up reminders
                  agent: ag_8d7c6b5a-4e3f-4a2b-9c1d-0e9f8a7b6c5d
                  callKind: service
                  tags:
                    - due-checkup
                  timezone: Asia/Kolkata
                  callingHours:
                    opens: '10:00'
                    closes: '19:00'
                  callDays:
                    - 1
                    - 2
                    - 3
                    - 4
                    - 5
                    - 6
                  skipDates:
                    - '2026-10-20'
                  maxCallsPerHour: 60
                  retryDelaysMinutes:
                    - 60
                    - 1440
                  retryAt: '11:00'
                  voicemailMessage: >-
                    Hello, this is Asha from Sunrise Dental Clinic. Your
                    six-month check-up is due — please call us back to book a
                    time.
                  scheduledAt: '2026-10-07T04:30:00Z'
      responses:
        '201':
          description: >-
            Created. The campaign as Get Campaign shows it, plus `message`: how
            many people it will reach, that it started, or why a requested
            launch did not happen (the campaign is then a draft you can launch
            later).
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CampaignResult'
              examples:
                broadcast:
                  summary: A broadcast created and launched
                  value:
                    id: cmp_9a3b7c21-4d5e-4f60-8a1b-2c3d4e5f6a7b
                    agent: ag_5c4a5f93-2b1e-4c0a-9d3f-7e8a1b2c3d4e
                    name: Diwali sale — VIP customers
                    kind: whatsapp
                    status: sending
                    template: diwali_offer_v2
                    purpose: null
                    counts:
                      recipients: 412
                      sent: 0
                      delivered: 0
                      read: 0
                      replied: 0
                      failed: 0
                      skipped: 0
                    scheduledAt: null
                    startedAt: '2026-10-06T10:00:02.311Z'
                    finishedAt: null
                    createdAt: '2026-10-06T10:00:01.874Z'
                    lastError: null
                    message: Sending started. Messages go out in the background.
                calling:
                  summary: A calling campaign scheduled
                  value:
                    id: cmp_1f2e3d4c-5b6a-4798-8a7b-6c5d4e3f2a1b
                    agent: ag_8d7c6b5a-4e3f-4a2b-9c1d-0e9f8a7b6c5d
                    name: Six-month check-up reminders
                    kind: voice
                    status: draft
                    template: null
                    purpose: Hello, this is Asha calling from Sunrise Dental Clinic.
                    counts:
                      recipients: 180
                      sent: 0
                      delivered: 0
                      read: 0
                      replied: 0
                      failed: 0
                      skipped: 0
                    scheduledAt: '2026-10-07T04:30:00.000Z'
                    startedAt: null
                    finishedAt: null
                    createdAt: '2026-10-06T10:00:01.874Z'
                    lastError: null
                    message: Created. 180 people will receive it.
                launchRefused:
                  summary: Launch asked for, refused, kept as a draft
                  value:
                    id: cmp_9a3b7c21-4d5e-4f60-8a1b-2c3d4e5f6a7b
                    agent: ag_5c4a5f93-2b1e-4c0a-9d3f-7e8a1b2c3d4e
                    name: Diwali sale — VIP customers
                    kind: whatsapp
                    status: draft
                    template: diwali_offer_v2
                    purpose: null
                    counts:
                      recipients: 412
                      sent: 0
                      delivered: 0
                      read: 0
                      replied: 0
                      failed: 0
                      skipped: 0
                    scheduledAt: null
                    startedAt: null
                    finishedAt: null
                    createdAt: '2026-10-06T10:00:01.874Z'
                    lastError: null
                    message: >-
                      Saved as a draft — Your balance is ₹0.40, and one message
                      costs ₹0.88. Add money to send this campaign.
        '400':
          description: >-
            A field is missing, has the wrong type or is out of range, or does
            not apply to this `kind` (a calling setting on a broadcast, a
            template on a calling campaign). The message names the field.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: '`callDays` does not apply to a broadcast.'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: >-
            No agent, template or `followUp` campaign by that id or name in this
            workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That template was not found.
        '409':
          description: >-
            The template's name exists in more than one language, so pass
            `language`; or the workspace has no agent yet.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That template exists in 2 languages (en, hi). Pass `language`.
        '422':
          description: >-
            The campaign cannot run as described, in the console's words:
            WhatsApp is not connected, the template is not approved, a blank has
            nothing filling it, an offer's countdown is missing or already past,
            the agent has no number or does not answer phone calls, a number
            cannot dial out or is not licensed for this kind of call, or a
            voicemail message was given and none of the agent's numbers can
            detect an answering machine.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: Nothing fills {{2}} in the message.
        '429':
          $ref: '#/components/responses/TooManyRequests'
components:
  parameters:
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
    CampaignCreate:
      description: A WhatsApp broadcast or a calling campaign, told apart by `kind`.
      oneOf:
        - $ref: '#/components/schemas/CampaignCreateBroadcast'
        - $ref: '#/components/schemas/CampaignCreateCalling'
      discriminator:
        propertyName: kind
        mapping:
          whatsapp: '#/components/schemas/CampaignCreateBroadcast'
          voice: '#/components/schemas/CampaignCreateCalling'
    CampaignResult:
      description: The campaign, plus a sentence about what just happened.
      allOf:
        - $ref: '#/components/schemas/Campaign'
        - type: object
          required:
            - message
          properties:
            message:
              type: string
              description: >-
                What happened, in a sentence you can show a person: how many
                people it will reach, that sending or calling started (and, when
                the balance covers only part of it, how far it goes), or — on
                create with `launch: true` — why the launch was refused and the
                campaign kept as a draft.
              example: Created. 412 people will receive it.
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
    CampaignCreateBroadcast:
      type: object
      title: WhatsApp broadcast
      description: >-
        One approved template to everyone in the audience. Calling settings
        (`callKind`, `callingHours`, `callDays`, `timezone`,
        `retryDelaysMinutes`, `retryDelaysBusyMinutes`, `retryAt`,
        `maxCallsPerHour`, `skipDates`, `endsAt`, `voicemailMessage`) are
        refused here.
      required:
        - kind
        - name
        - template
      properties:
        kind:
          type: string
          const: whatsapp
          description: '`whatsapp` for a broadcast.'
        name:
          type: string
          minLength: 2
          maxLength: 120
          description: What the console lists it as. Runs of spaces are collapsed.
          example: Diwali sale — VIP customers
        template:
          type: string
          description: >-
            The name of an **approved** template in this workspace (List
            Templates).
          example: diwali_offer_v2
        language:
          type: string
          description: >-
            The template's language. Needed only when the name exists in more
            than one language.
          example: en
        agent:
          type: string
          description: >-
            The agent that answers replies to this broadcast (`ag_…`). Leave it
            out and the agent on your connected WhatsApp number answers.
          example: ag_5c4a5f93-2b1e-4c0a-9d3f-7e8a1b2c3d4e
        variables:
          type: array
          maxItems: 20
          items:
            $ref: '#/components/schemas/CampaignVariable'
          description: >-
            What fills each blank. Every `{{n}}` in the body, and the blank in a
            link button's address, must be filled.
        offerExpiresAt:
          type: string
          format: date-time
          description: >-
            When the offer's countdown ends. Required, and in the future, when
            the template counts down to an offer.
        audience:
          $ref: '#/components/schemas/CampaignAudience'
          default: whatsapp_consented
        tags:
          type: array
          items:
            type: string
          description: >-
            Reach only contacts carrying at least one of these tags. Narrows the
            audience, never widens it. Tags are lower-cased, spaces become
            hyphens, and at most 20 are kept. To aim at your own list, add the
            contacts with Create Contact and a tag first.
          example:
            - vip
        followUp:
          $ref: '#/components/schemas/CampaignFollowUp'
        scheduledAt:
          type: string
          format: date-time
          description: >-
            Start the campaign by itself at this time, in the future. Do not
            send it together with `launch`.
        launch:
          type: boolean
          default: false
          description: >-
            `true` also starts it now, with Launch Campaign's checks. A refused
            launch keeps the draft and `message` says why.
    CampaignCreateCalling:
      type: object
      title: Calling campaign
      description: >-
        An agent phones each person in the audience from its own number.
        `template`, `language`, `variables` and `offerExpiresAt` are refused
        here.
      required:
        - kind
        - name
        - agent
      properties:
        kind:
          type: string
          const: voice
          description: '`voice` for a calling campaign.'
        name:
          type: string
          minLength: 2
          maxLength: 120
          description: What the console lists it as. Runs of spaces are collapsed.
          example: Six-month check-up reminders
        agent:
          type: string
          description: >-
            The agent that makes the calls (`ag_…`). It needs a phone number
            pointed at it, set to answer phone calls, and every number it calls
            from must be able to dial out and be licensed for `callKind`. Its
            opening line becomes the campaign's `purpose`.
          example: ag_8d7c6b5a-4e3f-4a2b-9c1d-0e9f8a7b6c5d
        callKind:
          type: string
          enum:
            - service
            - promotional
          default: service
          description: >-
            What the calls are for. A number may carry only the kinds of call it
            is licensed for; promotional calls need a number licensed for them.
        audience:
          $ref: '#/components/schemas/CampaignAudience'
          default: consented
        tags:
          type: array
          items:
            type: string
          description: >-
            Reach only contacts carrying at least one of these tags. Narrows the
            audience, never widens it. Tags are lower-cased, spaces become
            hyphens, and at most 20 are kept.
          example:
            - due-checkup
        followUp:
          $ref: '#/components/schemas/CampaignFollowUp'
        timezone:
          type: string
          maxLength: 64
          description: >-
            The IANA time zone that `callingHours`, `callDays`, `retryAt` and
            `skipDates` are read in. Leave it out to use your workspace's.
          example: Asia/Kolkata
        callingHours:
          $ref: '#/components/schemas/CampaignCallingHours'
        callDays:
          type: array
          minItems: 1
          items:
            type: integer
            minimum: 1
            maximum: 7
          description: >-
            The weekdays calls may be placed on, ISO numbering: 1 is Monday, 7
            is Sunday. Leave it out to call on any day.
          example:
            - 1
            - 2
            - 3
            - 4
            - 5
        skipDates:
          type: array
          maxItems: 60
          items:
            type: string
            format: date
          description: Dates (`YYYY-MM-DD`) on which no calls are placed, such as holidays.
          example:
            - '2026-10-20'
        maxCallsPerHour:
          type: integer
          minimum: 1
          maximum: 10000
          description: >-
            At most this many calls in any hour. It only slows the campaign
            down; your plan's call lines are still the limit.
          example: 60
        retryDelaysMinutes:
          type: array
          maxItems: 10
          items:
            type: integer
            minimum: 1
            maximum: 10080
          description: >-
            When nobody answers, call again after each of these waits, in
            minutes (up to a week each). `[60, 1440]` means two more tries.
          example:
            - 60
            - 1440
        retryDelaysBusyMinutes:
          type: array
          maxItems: 10
          items:
            type: integer
            minimum: 1
            maximum: 10080
          description: >-
            The same, for a line that was busy. Leave it out to use
            `retryDelaysMinutes`.
        retryAt:
          type: string
          pattern: ^\d{1,2}:\d{2}$
          description: >-
            `HH:MM`: a retry for an unanswered call happens at this time of day
            instead of after a fixed wait. Used only together with
            `retryDelaysMinutes`.
          example: '11:00'
        endsAt:
          type: string
          format: date-time
          description: No calls are placed after this time. Must be in the future.
        voicemailMessage:
          type: string
          maxLength: 600
          description: >-
            Left when an answering machine picks up. Refused when none of the
            agent's numbers can tell that a machine answered; when only some
            can, the campaign runs and `message` says how many cannot.
        scheduledAt:
          type: string
          format: date-time
          description: >-
            Start the campaign by itself at this time, in the future. Do not
            send it together with `launch`.
        launch:
          type: boolean
          default: false
          description: >-
            `true` also starts it now, with Launch Campaign's checks. A refused
            launch keeps the draft and `message` says why.
    Campaign:
      type: object
      description: A WhatsApp broadcast or a calling campaign, with its results.
      required:
        - id
        - agent
        - name
        - kind
        - status
        - template
        - purpose
        - counts
        - scheduledAt
        - startedAt
        - finishedAt
        - createdAt
        - lastError
      properties:
        id:
          type: string
          description: The campaign's id.
          example: cmp_9a3b7c21-4d5e-4f60-8a1b-2c3d4e5f6a7b
        agent:
          type: string
          description: >-
            A calling campaign: the agent that makes the calls. A broadcast: the
            agent that answers replies to it.
          example: ag_5c4a5f93-2b1e-4c0a-9d3f-7e8a1b2c3d4e
        name:
          type: string
          description: The campaign's name, as the console lists it.
        kind:
          type: string
          enum:
            - whatsapp
            - voice
          description: '`whatsapp` for a broadcast, `voice` for a calling campaign.'
        status:
          type: string
          enum:
            - draft
            - sending
            - paused
            - sent
            - failed
            - cancelled
          description: >-
            `draft` until launched (a scheduled campaign stays a draft until
            `scheduledAt`), `sending` while it runs, `paused` when stopped for
            now, then `sent`, `failed` (it could not run; see `lastError`) or
            `cancelled`.
        template:
          type:
            - string
            - 'null'
          description: A broadcast's template name. `null` on a calling campaign.
        purpose:
          type:
            - string
            - 'null'
          description: >-
            A calling campaign's opening line: the sentence the agent opens each
            call with, copied from the agent when the campaign was created
            (editing the agent later does not change it). `null` on a broadcast.
        counts:
          $ref: '#/components/schemas/CampaignCounts'
        scheduledAt:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When a scheduled campaign starts itself. `null` when it is started
            by hand.
        startedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it started sending. `null` while a draft.
        finishedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it finished or was cancelled. `null` while it can still send.
        createdAt:
          type: string
          format: date-time
          description: When it was created.
        lastError:
          type:
            - string
            - 'null'
          description: >-
            Why the campaign last stopped or failed, when it did. Cleared when
            it is launched or resumed.
    CampaignVariable:
      type: object
      description: What fills one `{{n}}` blank of the template, for each person.
      required:
        - position
        - source
      properties:
        position:
          type: integer
          minimum: 1
          maximum: 20
          description: 'The blank''s number: 1 fills `{{1}}`.'
          example: 1
        source:
          type: string
          enum:
            - contact_name
            - contact_email
            - contact_phone
            - fixed
          description: >-
            Where the value comes from: the contact's name, email or phone
            number, or `fixed` for the same `value` for everyone.
        value:
          type: string
          maxLength: 500
          description: >-
            The text for a `fixed` blank. Required when `source` is `fixed`;
            ignored otherwise.
        target:
          type: string
          enum:
            - body
            - button
          default: body
          description: >-
            `body` for a blank in the message, `button` for the blank at the end
            of a link button's address.
    CampaignAudience:
      type: string
      enum:
        - whatsapp_consented
        - consented
        - imported
        - everyone
      description: >-
        Which contacts the campaign draws from. `whatsapp_consented`: people who
        messaged you on WhatsApp and agreed to hear from you — the safest list,
        and a broadcast's default. `consented`: everyone who agreed to
        marketing, on any channel — a calling campaign's default. `imported`:
        contacts that came from your own imports; they may never have contacted
        you. `everyone`: every contact with a number. People who asked not to be
        contacted are left out whichever you choose.
    CampaignFollowUp:
      type: object
      description: >-
        Reach the people from an earlier campaign who answered it a certain way.
        Both fields, or leave the whole object out.
      required:
        - campaign
        - outcome
      properties:
        campaign:
          type: string
          description: The earlier campaign's id (`cmp_…`), in this workspace.
          example: cmp_9a3b7c21-4d5e-4f60-8a1b-2c3d4e5f6a7b
        outcome:
          type: string
          enum:
            - no_reply
            - replied
            - not_delivered
            - failed
          description: >-
            Who to reach: those who did not reply, those who replied, those it
            was not delivered to, or those it failed for.
    CampaignCallingHours:
      type: object
      description: The window calls may be placed in each day, read in `timezone`.
      required:
        - opens
        - closes
      properties:
        opens:
          type: string
          pattern: ^\d{1,2}:\d{2}$
          description: When calling starts, `HH:MM`.
          example: '10:00'
        closes:
          type: string
          pattern: ^\d{1,2}:\d{2}$
          description: >-
            When calling stops, `HH:MM`, later than `opens`. `24:00` means the
            end of the day.
          example: '19:00'
    CampaignCounts:
      type: object
      description: How far the campaign has got, person by person.
      required:
        - recipients
        - sent
        - delivered
        - read
        - replied
        - failed
        - skipped
      properties:
        recipients:
          type: integer
          minimum: 0
          description: People in the audience, counted when the campaign was created.
        sent:
          type: integer
          minimum: 0
          description: Messages handed to WhatsApp, or calls placed.
        delivered:
          type: integer
          minimum: 0
          description: >-
            Messages WhatsApp reports as delivered. Broadcasts only; a calling
            campaign leaves it at 0.
        read:
          type: integer
          minimum: 0
          description: Messages WhatsApp reports as read. Never more than `delivered`.
        replied:
          type: integer
          minimum: 0
          description: People who wrote back after receiving it.
        failed:
          type: integer
          minimum: 0
          description: People it could not reach.
        skipped:
          type: integer
          minimum: 0
          description: >-
            People left out at send time, for example because they asked not to
            be contacted after the audience was built.
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