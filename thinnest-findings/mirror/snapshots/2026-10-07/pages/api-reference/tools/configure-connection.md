> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Connection

> Pin a connection to its target, say how a lead's row is found, choose when it saves, and switch its tools. The account must be connected first (records excepted). Changes apply in a fixed order and stop at the first refusal, keeping what came before it. Helpdesks have nothing to configure. A **build** key may do this.



## OpenAPI

````yaml /api-reference/openapi.json patch /agents/{id}/connections/{kind}
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
    patch:
      tags:
        - Tools
      summary: Configure Connection
      description: >-
        Pin a connection to its target, say how a lead's row is found, choose
        when it saves, and switch its tools. The account must be connected first
        (records excepted). Changes apply in a fixed order and stop at the first
        refusal, keeping what came before it. Helpdesks have nothing to
        configure. A **build** key may do this.
      operationId: configureConnection
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateToolConnectionRequest'
            examples:
              calcom:
                summary: calcom
                value:
                  tools:
                    calcom_check_availability: true
                    calcom_book_meeting: true
                  phrases:
                    calcom_check_availability:
                      before: Let me look at the calendar.
                      after: null
              grist:
                summary: grist
                value:
                  target:
                    doc: 8xQm2KvTzR4pLw
                    table: Site_Visits
                  match:
                    column: Phone
                    type: phone
                  variableColumns:
                    Locality: locality
                  mode: tool
                  runAsync: false
                  tools:
                    grist_save_row: true
              googlesheets:
                summary: googlesheets
                value:
                  target:
                    spreadsheet: 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms
                    sheet: Leads
                  match:
                    column: Mobile
                    type: phone
                  tools:
                    GOOGLESHEETS_LOOKUP_SPREADSHEET_ROW: true
              zoho:
                summary: zoho
                value:
                  target:
                    module: Leads
                  match:
                    column: Mobile
                    type: phone
                  mode: tool
                  tools:
                    zoho_save_lead: true
                    zoho_find_lead: true
              zoho_bigin:
                summary: zoho_bigin
                value:
                  target:
                    module: Contacts
                  tools:
                    bigin_save_contact: true
              records:
                summary: records
                value:
                  fields:
                    - Name
                    - City | where they live
                    - Budget | in lakhs
                    - Visit date
                  mode: tool
                  tools:
                    record_save_row: true
      responses:
        '200':
          description: The connection as saved, with what each change said.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ToolConnectionUpdated'
              example:
                kind: grist
                name: Grist
                signIn: key
                available: true
                connected: true
                account:
                  email: ops@greenleafrealty.in
                  name: null
                lastError: null
                mode: tool
                runAsync: false
                target:
                  doc: 8xQm2KvTzR4pLw
                  table: Site_Visits
                  columns:
                    - Name
                    - Phone
                    - Budget
                    - Locality
                    - Visit_Date
                match:
                  column: Phone
                  type: phone
                variableColumns:
                  Locality: locality
                tools:
                  - id: grist_save_row
                    title: Fill in a row
                    summary: >-
                      Adds or fills the lead's row in your table as the
                      conversation goes.
                    writes: true
                    enabled: true
                    phrases:
                      before: null
                      after: null
                  - id: grist_find_rows
                    title: Look something up
                    summary: Reads rows from your table to answer a question.
                    writes: false
                    enabled: false
                    phrases:
                      before: null
                      after: null
                toolsInUse: 5
                maxTools: 500
                messages:
                  - Every conversation now fills the row that matches Phone.
        '400':
          description: A field is wrong for this kind, or the provider refused it.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                helpdesk:
                  summary: Helpdesk
                  value:
                    error: >-
                      A helpdesk has nothing to configure — POST to reconnect
                      it, or DELETE to disconnect.
                target:
                  summary: Incomplete target
                  value:
                    error: '`target` needs `doc` and `table`.'
                tool:
                  summary: Not this connection's tool
                  value:
                    error: '`zoho_save_lead` is not one of this connection''s tools.'
                column:
                  summary: Unknown column
                  value:
                    error: >-
                      That column is not in the table any more. Choose the table
                      again.
                empty:
                  summary: Empty body
                  value:
                    error: >-
                      Nothing to change — the body named no field this
                      connection takes.
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
          description: >-
            Not connected yet, a target is needed first, or the tool budget is
            spent.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                browser:
                  summary: Browser sign-in needed
                  value:
                    error: Sign in to that account in the console first.
                connect:
                  summary: Not connected
                  value:
                    error: Connect that account first.
                table:
                  summary: No table
                  value:
                    error: Choose a table first.
                budget:
                  summary: Budget spent
                  value:
                    error: >-
                      An agent can have 500 connected tools at once, across all
                      your connections. Turn one off to make room — every extra
                      tool makes the agent worse at choosing between them.
        '429':
          $ref: '#/components/responses/TooManyRequests'
        '502':
          description: The account could not be read.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: 'Could not read that sheet''s header row: permission denied.'
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
    UpdateToolConnectionRequest:
      type: object
      description: >-
        Any of these, as the kind allows. Applied in this order — fields,
        target, match, variableColumns, mode, runAsync, tools, phrases —
        stopping at the first refusal; what came before it is kept, and the
        refusal says so. Helpdesks (`zendesk`, `salesforce`) have nothing to
        configure.
      properties:
        fields:
          oneOf:
            - type: array
              items:
                type: string
            - type: string
          description: 'Records only: what to collect, `Label` or `Label | what it means`.'
        target:
          type: object
          description: >-
            Spreadsheets and CRMs: pins it and reads the target's real columns.
            Grist needs `doc` and `table`; Google Sheets `spreadsheet` and
            `sheet`; Zoho CRM and Bigin `module`. Use `GET …/options` to see the
            choices.
          properties:
            doc:
              type: string
              description: 'Grist: the document id.'
            table:
              type: string
              description: 'Grist: the table id.'
            spreadsheet:
              type: string
              description: 'Google Sheets: the spreadsheet id or link.'
            sheet:
              type: string
              description: 'Google Sheets: the sheet (tab) name.'
            module:
              type: string
              description: 'Zoho: the module''s API name, e.g. `Leads`.'
        match:
          type:
            - object
            - 'null'
          description: >-
            Spreadsheets and CRMs: fill the lead's existing row found by this
            column instead of adding one. Null (or `column: null`) adds a row
            per conversation.
          properties:
            column:
              type:
                - string
                - 'null'
              description: A column of the pinned target.
            type:
              type: string
              description: '`phone` compares numbers loosely; `exact` compares text exactly.'
              enum:
                - phone
                - exact
              default: phone
        variableColumns:
          type: object
          additionalProperties:
            type: string
          description: >-
            Spreadsheets and CRMs: column to campaign variable, e.g. `{
            "Locality": "locality" }`. Neither may contain `=` or a line break.
            Replaces the saved map.
        mode:
          type: string
          description: >-
            All but the calendar: `tool` saves during the conversation; `parser`
            reads the conversation afterwards (and switches the save tool off).
          enum:
            - tool
            - parser
        runAsync:
          type: boolean
          description: 'Grist only: answer before the save finishes.'
        tools:
          type: object
          additionalProperties:
            type: boolean
          description: >-
            Tool id to `true` or `false`. Every id must be one of this
            connection's tools. Switching on counts against the shared
            `maxTools` budget.
        phrases:
          type: object
          description: >-
            Tool id to `{ before, after }`: what the agent says on a call while
            the tool runs. Up to 8 lines, each under 60 characters.
          additionalProperties:
            type: object
            properties:
              before:
                type:
                  - string
                  - 'null'
                description: Said while it waits.
              after:
                type:
                  - string
                  - 'null'
                description: Said after.
    ToolConnectionUpdated:
      allOf:
        - $ref: '#/components/schemas/ToolConnectionDetail'
        - type: object
          required:
            - messages
          properties:
            messages:
              type: array
              items:
                type: string
              description: What each applied change said, in order.
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