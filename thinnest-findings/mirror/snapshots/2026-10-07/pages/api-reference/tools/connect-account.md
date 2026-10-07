> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Connect Account

> Connect (or re-key) an account. Every key, token and secret is sealed and never returned. Connecting grants nothing: tools start off and are switched with `PATCH` `tools`. `googlesheets`, `zoho` and `zoho_bigin` sign in on the provider's own consent screen — connect them once in the console (this answers `409`), then configure them here. A helpdesk connect opens one test ticket or case and answers with `inbound` **once**; a records connect that makes the first link answers with `link.passcode` **once**. A **build** key may do this.



## OpenAPI

````yaml /api-reference/openapi.json post /agents/{id}/connections/{kind}
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
  /agents/{id}/connections/{kind}:
    parameters:
      - $ref: '#/components/parameters/ToolsAgentIdParam'
      - $ref: '#/components/parameters/ToolsConnectionKindParam'
    post:
      tags:
        - Tools
      summary: Connect Account
      description: >-
        Connect (or re-key) an account. Every key, token and secret is sealed
        and never returned. Connecting grants nothing: tools start off and are
        switched with `PATCH` `tools`. `googlesheets`, `zoho` and `zoho_bigin`
        sign in on the provider's own consent screen — connect them once in the
        console (this answers `409`), then configure them here. A helpdesk
        connect opens one test ticket or case and answers with `inbound`
        **once**; a records connect that makes the first link answers with
        `link.passcode` **once**. A **build** key may do this.
      operationId: connectAccount
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ConnectToolConnectionRequest'
            examples:
              calcom:
                summary: calcom
                value:
                  apiKey: cal_live_3f9a1c…
              grist:
                summary: grist
                value:
                  apiKey: 7e2b94d1c0…
              records:
                summary: records
                value:
                  fields:
                    - Name
                    - City | where they live
                    - Budget | in lakhs
              zendesk:
                summary: zendesk
                value:
                  subdomain: urbanloom
                  email: support@urbanloom.in
                  apiToken: Zt8kP2…
              salesforce:
                summary: salesforce
                value:
                  instanceUrl: https://greenleafrealty.my.salesforce.com
                  clientId: 3MVG9…
                  clientSecret: B7F2…
      responses:
        '201':
          description: >-
            Connected. `inbound` (helpdesks) and `link.passcode` (a new records
            link) appear only here.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ToolConnectionConnected'
              examples:
                calcom:
                  summary: calcom
                  value:
                    kind: calcom
                    name: Cal.com
                    signIn: key
                    available: true
                    connected: true
                    account:
                      email: frontdesk@sunrisedental.in
                      name: Sunrise Dental
                    timezone: Asia/Kolkata
                    lastError: null
                    tools:
                      - id: calcom_list_event_types
                        title: See what can be booked
                        summary: See what can be booked.
                        writes: false
                        enabled: false
                        phrases:
                          before: null
                          after: null
                      - id: calcom_check_availability
                        title: Check when you are free
                        summary: Check when you are free.
                        writes: false
                        enabled: false
                        phrases:
                          before: Let me look at the calendar.
                          after: null
                      - id: calcom_hold_slot
                        title: Hold a slot while you talk
                        summary: Hold a slot while you talk.
                        writes: true
                        enabled: false
                        phrases:
                          before: null
                          after: null
                      - id: calcom_book_meeting
                        title: Book the meeting
                        summary: Book the meeting.
                        writes: true
                        enabled: false
                        phrases:
                          before: null
                          after: null
                      - id: calcom_find_booking
                        title: Find their existing booking
                        summary: Find their existing booking.
                        writes: false
                        enabled: false
                        phrases:
                          before: null
                          after: null
                      - id: calcom_reschedule_booking
                        title: Move a booking
                        summary: Move a booking.
                        writes: true
                        enabled: false
                        phrases:
                          before: null
                          after: null
                      - id: calcom_cancel_booking
                        title: Cancel a booking
                        summary: Cancel a booking.
                        writes: true
                        enabled: false
                        phrases:
                          before: null
                          after: null
                    toolsInUse: 0
                    maxTools: 500
                    message: Connected.
                records:
                  summary: records
                  value:
                    kind: records
                    name: Records here
                    signIn: none
                    available: true
                    connected: true
                    account: null
                    lastError: null
                    mode: tool
                    tools:
                      - id: record_save_row
                        title: Fill in a record
                        summary: >-
                          Fills in this conversation's record with the details
                          you asked for.
                        writes: true
                        enabled: false
                        phrases:
                          before: null
                          after: null
                    fields:
                      - id: Name
                        label: Name
                        description: null
                      - id: City
                        label: City
                        description: where they live
                      - id: Budget
                        label: Budget
                        description: in lakhs
                    recordCount: 0
                    link:
                      url: https://app.thinnest.ai/r/k7Qm2xVb9TzPq4Lw
                      passcode: '482913'
                    toolsInUse: 0
                    maxTools: 500
                    message: >-
                      Collecting 3 details: Name, City, Budget. A link to read
                      them is below.
                zendesk:
                  summary: zendesk
                  value:
                    kind: zendesk
                    name: Zendesk
                    signIn: key
                    available: true
                    connected: true
                    account:
                      host: urbanloom.zendesk.com
                      email: support@urbanloom.in
                    enabled: true
                    lastError: null
                    toolsInUse: 0
                    maxTools: 500
                    message: Connected. A test ticket was created — you can close it.
                    inbound:
                      url: >-
                        https://app.thinnest.ai/api/tickets/zendesk?c=7c1e4b20-93d5-4a6f-8e02-b5d9c3a1f478
                      secret: whsec_Qm4xT9…
        '400':
          description: A required field is missing, or the provider refused the credential.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                missing:
                  summary: Missing field
                  value:
                    error: '`apiKey` is required.'
                fields:
                  summary: Records without fields
                  value:
                    error: >-
                      `fields` is required — a list of what to collect, like
                      ["Name", "City | where they live"].
                subdomain:
                  summary: Bad subdomain
                  value:
                    error: Enter just the subdomain — the 'acme' in acme.zendesk.com.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: The agent is not in this workspace, or `kind` is not a connection.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                agent:
                  summary: Agent
                  value:
                    error: That agent was not found.
                kind:
                  summary: Kind
                  value:
                    error: That kind of connection was not found.
        '409':
          description: This kind signs in through a browser, which the API cannot do.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  This account signs in through a browser consent screen, which
                  the API cannot do. Connect it once in the console, then pin,
                  configure and switch its tools here.
        '429':
          $ref: '#/components/responses/TooManyRequests'
        '503':
          description: This deployment cannot store credentials.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  This deployment has no secret key configured, so a key cannot
                  be stored safely.
components:
  parameters:
    ToolsAgentIdParam:
      name: id
      in: path
      required: true
      description: The agent's id (`ag_…`).
      schema:
        type: string
      example: ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34
    ToolsConnectionKindParam:
      name: kind
      in: path
      required: true
      description: >-
        The connection: `calcom` (calendar), `grist` or `googlesheets`
        (spreadsheets), `zoho` or `zoho_bigin` (CRMs), `records` (kept here),
        `zendesk` or `salesforce` (helpdesks).
      schema:
        type: string
        enum:
          - calcom
          - grist
          - googlesheets
          - zoho
          - zoho_bigin
          - records
          - zendesk
          - salesforce
      example: grist
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
    ConnectToolConnectionRequest:
      description: >-
        The body depends on `{kind}`. `googlesheets`, `zoho` and `zoho_bigin`
        take no body here: they sign in through a browser in the console, and
        this answers `409`.
      oneOf:
        - $ref: '#/components/schemas/CalcomConnectRequest'
        - $ref: '#/components/schemas/GristConnectRequest'
        - $ref: '#/components/schemas/RecordsConnectRequest'
        - $ref: '#/components/schemas/ZendeskConnectRequest'
        - $ref: '#/components/schemas/SalesforceConnectRequest'
    ToolConnectionConnected:
      allOf:
        - $ref: '#/components/schemas/ToolConnectionDetail'
        - type: object
          required:
            - message
          properties:
            message:
              type: string
              description: What happened.
            inbound:
              type: object
              description: >-
                Helpdesks only, and **only in this response**: paste both into
                the helpdesk's webhook so replies reach the agent.
              properties:
                url:
                  type: string
                  description: The address the helpdesk should call.
                secret:
                  type: string
                  description: The secret it should sign with.
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
    CalcomConnectRequest:
      title: calcom
      type: object
      required:
        - apiKey
      properties:
        apiKey:
          type: string
          description: >-
            A live Cal.com API key (`cal_live_…`), from Settings → Developer →
            API keys. Write-only.
    GristConnectRequest:
      title: grist
      type: object
      required:
        - apiKey
      properties:
        apiKey:
          type: string
          description: >-
            A Grist API key, from Account settings → Developer → API keys.
            Write-only.
    RecordsConnectRequest:
      title: records
      type: object
      required:
        - fields
      properties:
        fields:
          oneOf:
            - type: array
              items:
                type: string
            - type: string
          description: >-
            What to collect, one per entry — `Label` or `Label | what it means`.
            A string with one per line is accepted too.
    ZendeskConnectRequest:
      title: zendesk
      type: object
      required:
        - subdomain
        - email
        - apiToken
      properties:
        subdomain:
          type: string
          description: Just the subdomain — the `acme` in acme.zendesk.com.
        email:
          type: string
          description: The email address the API token belongs to.
          format: email
        apiToken:
          type: string
          description: The API token. Write-only.
    SalesforceConnectRequest:
      title: salesforce
      type: object
      required:
        - instanceUrl
        - clientId
        - clientSecret
      properties:
        instanceUrl:
          type: string
          description: Your instance URL, like https://acme.my.salesforce.com.
          format: uri
        clientId:
          type: string
          description: The connected app's consumer key.
        clientSecret:
          type: string
          description: The connected app's consumer secret. Write-only.
    ToolConnectionDetail:
      allOf:
        - $ref: '#/components/schemas/ToolConnection'
        - type: object
          required:
            - toolsInUse
            - maxTools
          properties:
            toolsInUse:
              type: integer
              description: Connection tools switched on, across every connection.
            maxTools:
              type: integer
              description: The shared budget.
    ToolConnection:
      type: object
      description: >-
        One account an agent can work in. Fields beyond the first few depend on
        the kind: a calendar has `timezone`; spreadsheets and CRMs have
        `target`, `match` and `variableColumns`; records has `fields`,
        `recordCount` and `link`; a helpdesk has only `account` and `enabled`.
        Credentials never appear.
      required:
        - kind
        - name
        - signIn
        - available
        - connected
        - account
        - lastError
      properties:
        kind:
          type: string
          description: The connection.
          enum:
            - calcom
            - grist
            - googlesheets
            - zoho
            - zoho_bigin
            - records
            - zendesk
            - salesforce
        name:
          type: string
          description: Its display name.
        signIn:
          type: string
          description: >-
            How it is connected: `key` by `POST` with a key; `browser` through a
            consent screen in the console (the API cannot); `none` for records,
            which need no account.
          enum:
            - key
            - browser
            - none
        available:
          type: boolean
          description: Whether this deployment offers it at all.
        connected:
          type: boolean
          description: Whether it is connected.
        signInPending:
          type: boolean
          description: >-
            Browser sign-ins only: a sign-in was started in the console and not
            finished.
        account:
          type:
            - object
            - 'null'
          description: >-
            Who it is connected as: `{ email, name }`, or `{ host, email }` for
            a helpdesk.
          properties:
            email:
              type:
                - string
                - 'null'
              description: The account's email.
            name:
              type:
                - string
                - 'null'
              description: The account's name.
            host:
              type: string
              description: The helpdesk's host.
        timezone:
          type:
            - string
            - 'null'
          description: 'Calendar only: the account''s timezone.'
        lastError:
          type:
            - string
            - 'null'
          description: Why the last attempt to use it failed.
        mode:
          type: string
          description: >-
            All but the calendar and helpdesks: `tool` saves during the
            conversation; `parser` reads the conversation afterwards.
          enum:
            - tool
            - parser
        runAsync:
          type: boolean
          description: 'Grist only: answer before the save finishes.'
        target:
          type: object
          description: >-
            Spreadsheets and CRMs: what it is pinned to, and that target's real
            columns. Grist `{ doc, table, columns }`; Google Sheets `{
            spreadsheet, sheet, columns }`; Zoho `{ module, columns }`.
          additionalProperties: true
        match:
          type:
            - object
            - 'null'
          description: >-
            Spreadsheets and CRMs: the column that finds a lead's existing row,
            or null to add a row per conversation.
          properties:
            column:
              type: string
              description: The column.
            type:
              type: string
              description: How it is compared.
              enum:
                - phone
                - exact
        variableColumns:
          type: object
          additionalProperties:
            type: string
          description: 'Spreadsheets and CRMs: column to campaign variable.'
        tools:
          type: array
          description: Its tools. Helpdesks have none here.
          items:
            $ref: '#/components/schemas/ToolConnectionTool'
        fields:
          type: array
          description: 'Records only: what is collected.'
          items:
            type: object
            properties:
              id:
                type: string
                description: The field's id.
              label:
                type: string
                description: Its label.
              description:
                type:
                  - string
                  - 'null'
                description: What it means, if given.
        recordCount:
          type: integer
          description: 'Records only: how many records have been collected.'
        link:
          type:
            - object
            - 'null'
          description: >-
            Records only: the link to read them. The passcode is shown only by
            the call that makes a link.
          properties:
            url:
              type: string
              description: The link.
            hasPasscode:
              type: boolean
              description: 'Always true: the link needs its passcode.'
            passcode:
              type: string
              description: Only in the response that made the link — never again.
        enabled:
          type: boolean
          description: 'Helpdesks only: whether it is in use.'
    ToolConnectionTool:
      type: object
      required:
        - id
        - title
        - summary
        - writes
        - enabled
        - phrases
      properties:
        id:
          type: string
          description: The tool's id, used as the key in `PATCH` `tools` and `phrases`.
        title:
          type: string
          description: Its name in the console.
        summary:
          type: string
          description: What it does.
        writes:
          type: boolean
          description: Whether calling it changes something in the account.
        enabled:
          type: boolean
          description: Whether it is switched on. Every tool starts off.
        phrases:
          type: object
          description: On calls, what the agent says while the tool runs.
          properties:
            before:
              type:
                - string
                - 'null'
              description: Said while it waits; one phrase per line.
            after:
              type:
                - string
                - 'null'
              description: Said after it answers.
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