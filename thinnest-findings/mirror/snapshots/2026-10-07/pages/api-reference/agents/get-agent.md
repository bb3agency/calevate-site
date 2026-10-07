> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Agent

> One agent: its instructions, model, languages, script, widget, call settings and the details it collects from calls. Which engine speaks its voice or runs its model is never part of the answer.



## OpenAPI

````yaml /api-reference/openapi.json get /agents/{id}
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
    get:
      tags:
        - Agents
      summary: Get Agent
      description: >-
        One agent: its instructions, model, languages, script, widget, call
        settings and the details it collects from calls. Which engine speaks its
        voice or runs its model is never part of the answer.
      operationId: getAgent
      parameters:
        - $ref: '#/components/parameters/Workspace'
      responses:
        '200':
          description: The agent.
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
                  Namaste, I'm calling from Skyline Homes about your enquiry for
                  Sky Towers.
                businessDescription: Skyline Homes builds 2 and 3 BHK apartments in Pune.
                model: prana-voice
                temperature: 0.3
                maxReplyTokens: 300
                language: Hindi
                secondLanguage: English
                escalation:
                  onNoAnswer: false
                  onRequest: true
                captureLeads: true
                scheduleCallbacks: false
                steps:
                  - title: Confirm the enquiry
                    detail: >-
                      Check they enquired about Sky Towers and are still
                      looking.
                    branches: []
                    collect: []
                  - title: Budget and size
                    detail: >-
                      Ask for their budget and whether they want a 2 BHK or a 3
                      BHK.
                    branches: []
                    collect: []
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
                  detectMachines: false
                  recordCalls: true
                  maxCallSeconds: 300
                  pastConversations: quiet
                collectFields:
                  - name: budget
                    type: number
                    description: Budget in rupees
                    choices: null
                  - name: interest
                    type: text
                    description: null
                    choices:
                      - Hot
                      - Warm
                      - Cold
                webKey: pk_9fQ2xLm7Rt4vWb8KcN3hYd6sJ1pZ
                createdAt: '2026-09-17T09:39:31.204Z'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          description: No such agent in your workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That agent was not found.
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
          description: A second language it may switch to, or null.
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
      properties:
        error:
          type: string
          description: What went wrong, in a sentence you can show a person.
      example:
        error: That agent was not found.
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
        - maxCallSeconds
        - pastConversations
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
            website, WhatsApp calls. Read-only; a number is attached in the
            console.
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
        maxCallSeconds:
          type:
            - integer
            - 'null'
          minimum: 60
          maximum: 1200
          description: >-
            The longest a call may run, in seconds; null for the default ceiling
            of 20 minutes.
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