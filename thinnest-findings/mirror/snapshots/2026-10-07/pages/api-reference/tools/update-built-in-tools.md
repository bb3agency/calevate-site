> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Update Built-in Tools

> Switch built-in tools on or off and set recall, code verification and the hand-over. `search_knowledge` is not a switch and web search cannot be switched on; both are refused. Changes apply in order and stop at the first refusal, keeping what came before. Needs a **full** key. — it can arm tools that call or message customers.



## OpenAPI

````yaml /api-reference/openapi.json patch /agents/{id}/tools
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
  /agents/{id}/tools:
    parameters:
      - $ref: '#/components/parameters/ToolsAgentIdParam'
    patch:
      tags:
        - Tools
      summary: Update Built-in Tools
      description: >-
        Switch built-in tools on or off and set recall, code verification and
        the hand-over. `search_knowledge` is not a switch and web search cannot
        be switched on; both are refused. Changes apply in order and stop at the
        first refusal, keeping what came before. Needs a **full** key. — it can
        arm tools that call or message customers.
      operationId: updateBuiltInTools
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/UpdateAgentBuiltInToolsRequest'
            example:
              tools:
                capture_lead: true
                escalate_to_human: true
                call_them_now: true
                send_whatsapp: false
              recall: two_tier
              handOver:
                mode: call
                phone: +91 98765 43210
                line: Connecting you to our front desk now.
      responses:
        '200':
          description: The tools as saved, with any notes.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/AgentBuiltInToolsUpdated'
              example:
                agent: ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34
                tools:
                  - id: search_knowledge
                    title: Search your knowledge base
                    summary: >-
                      Looks through your knowledge base before answering, and
                      quotes from it rather than guessing.
                    switchable: false
                    enabled: true
                    reachesOtherChannels: false
                  - id: capture_lead
                    title: Capture leads
                    summary: >-
                      Asks how to reach someone who shows real interest, and
                      records their details with a note on what they wanted.
                    switchable: true
                    enabled: true
                    reachesOtherChannels: false
                  - id: escalate_to_human
                    title: Hand over to a person
                    summary: >-
                      Flags the conversation for your team and tells the
                      customer someone will follow up.
                    switchable: true
                    enabled: true
                    reachesOtherChannels: false
                  - id: schedule_callback
                    title: Book a call back
                    summary: >-
                      When somebody asks to be called later — in half an hour,
                      after five — the agent books it and your number rings them
                      at that time.
                    switchable: true
                    enabled: false
                    reachesOtherChannels: false
                  - id: call_them_now
                    title: Ring the customer now
                    summary: >-
                      While the agent is talking to a customer on your website
                      or WhatsApp, it can have your number ring that customer
                      straight away.
                    switchable: true
                    enabled: true
                    reachesOtherChannels: true
                    ready: true
                    needs: >-
                      a number that can dial out, and the customer inside your
                      calling hours
                  - id: send_whatsapp
                    title: Send the customer a WhatsApp
                    summary: >-
                      While the agent is on a call with a customer, or chatting
                      on your website, it can send that customer one of your
                      approved templates on WhatsApp.
                    switchable: true
                    enabled: true
                    reachesOtherChannels: true
                    ready: false
                    needs: >-
                      an approved utility template — the agent cannot write its
                      own words on WhatsApp
                  - id: reply_by_email
                    title: Reply to the customer by email
                    summary: >-
                      The agent can answer on that customer's existing email
                      thread in your helpdesk, as you.
                    switchable: true
                    enabled: false
                    reachesOtherChannels: true
                    ready: false
                    needs: >-
                      a connected helpdesk that can send — Zendesk today, not
                      Salesforce
                webSearch:
                  enabled: false
                  switchable: false
                recall: two_tier
                verifyByCode: false
                handOver:
                  mode: call
                  phone: '+919876543210'
                  line: Connecting you to our front desk now.
                messages: []
        '400':
          description: A field is wrong.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                knowledge:
                  summary: search_knowledge
                  value:
                    error: >-
                      `search_knowledge` is not a switch — it is on whenever the
                      agent has knowledge.
                web:
                  summary: webSearch
                  value:
                    error: >-
                      Searching the web cannot be switched on here — the console
                      does not offer it either.
                unknown:
                  summary: Unknown tool
                  value:
                    error: >-
                      `book_table` is not a built-in tool. Switchable:
                      capture_lead, escalate_to_human, schedule_callback,
                      call_them_now, send_whatsapp, reply_by_email.
                phone:
                  summary: Bad number
                  value:
                    error: >-
                      Enter the number with its country code, like +91 98765
                      43210.
                nophone:
                  summary: Call without a number
                  value:
                    error: Add the number to put callers through to.
                empty:
                  summary: Empty body
                  value:
                    error: >-
                      Nothing to change — send `tools`, `recall`, `verifyByCode`
                      or `handOver`.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: The agent is not in this workspace.
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
    ToolsAgentIdParam:
      name: id
      in: path
      required: true
      description: The agent's id (`ag_…`).
      schema:
        type: string
      example: ag_3f6a9c21-7d4e-4b58-9a1f-0c2e8b7d5a34
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
    UpdateAgentBuiltInToolsRequest:
      type: object
      description: >-
        Send at least one field. Changes apply in order (tools, recall,
        verifyByCode, handOver) and stop at the first refusal; what came before
        it is kept, and the refusal says so.
      properties:
        tools:
          type: object
          description: >-
            Tool id to `true` or `false`. Switchable: `capture_lead`,
            `escalate_to_human`, `schedule_callback`, `call_them_now`,
            `send_whatsapp`, `reply_by_email`.
          properties:
            capture_lead:
              type: boolean
            escalate_to_human:
              type: boolean
            schedule_callback:
              type: boolean
            call_them_now:
              type: boolean
            send_whatsapp:
              type: boolean
            reply_by_email:
              type: boolean
          additionalProperties: false
        recall:
          type: string
          description: >-
            How much of a recognised customer's history the agent may use:
            `trusted` (all of it), `two_tier` (the default) or `verified` (only
            once they are confirmed).
          enum:
            - trusted
            - two_tier
            - verified
        verifyByCode:
          type: boolean
          description: >-
            Confirm a customer with a one-time WhatsApp code instead of their
            email.
        handOver:
          type: object
          description: Fields you leave out keep their saved value.
          properties:
            mode:
              type: string
              description: >-
                `chat` or `call`. A call needs a `phone` (sent now or already
                saved).
              enum:
                - chat
                - call
            phone:
              type:
                - string
                - 'null'
              description: >-
                The number to put callers through to, with its country code.
                Null clears it.
              maxLength: 40
            line:
              type:
                - string
                - 'null'
              description: >-
                What the agent says before putting a caller through. Null clears
                it.
              maxLength: 300
    AgentBuiltInToolsUpdated:
      allOf:
        - $ref: '#/components/schemas/AgentBuiltInTools'
        - type: object
          required:
            - messages
          properties:
            messages:
              type: array
              items:
                type: string
              description: Notes from the changes applied, in order; often empty.
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
    AgentBuiltInTools:
      type: object
      required:
        - agent
        - tools
        - webSearch
        - recall
        - verifyByCode
        - handOver
      properties:
        agent:
          type: string
          description: The agent (`ag_…`).
        tools:
          type: array
          items:
            $ref: '#/components/schemas/AgentBuiltInTool'
        webSearch:
          type: object
          description: Searching the web. Shown, never switchable here.
          properties:
            enabled:
              type: boolean
              description: Whether it is on.
            switchable:
              type: boolean
              const: false
        recall:
          type: string
          description: >-
            How much of a recognised customer's history from other channels the
            agent may use.
          enum:
            - trusted
            - two_tier
            - verified
        verifyByCode:
          type: boolean
          description: >-
            Whether a customer is confirmed with a one-time WhatsApp code rather
            than their email.
        handOver:
          type: object
          description: How a hand-over to a person happens.
          properties:
            mode:
              type: string
              description: >-
                `chat` flags the conversation for your team; `call` also puts a
                caller through to `phone`.
              enum:
                - chat
                - call
            phone:
              type:
                - string
                - 'null'
              description: The number callers are put through to, in E.164.
            line:
              type:
                - string
                - 'null'
              description: What the agent says before putting a caller through.
    AgentBuiltInTool:
      type: object
      required:
        - id
        - title
        - summary
        - switchable
        - enabled
        - reachesOtherChannels
      properties:
        id:
          type: string
          description: The tool's id.
          enum:
            - search_knowledge
            - capture_lead
            - escalate_to_human
            - schedule_callback
            - call_them_now
            - send_whatsapp
            - reply_by_email
        title:
          type: string
          description: Its name in the console.
        summary:
          type: string
          description: What it does, in one sentence.
        switchable:
          type: boolean
          description: >-
            Whether `PATCH` may switch it. `search_knowledge` is not a switch:
            it is on whenever the agent has knowledge.
        enabled:
          type: boolean
          description: Whether it is switched on.
        reachesOtherChannels:
          type: boolean
          description: >-
            Whether it contacts the customer on another channel (a call, a
            WhatsApp, an email).
        ready:
          type: boolean
          description: >-
            Only on the three tools that reach other channels: on **and** what
            it needs exists, so it will really attach.
        needs:
          type:
            - string
            - 'null'
          description: >-
            Only on the three tools that reach other channels: what must also be
            true, in plain words.
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