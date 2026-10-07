> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Get Customers Usage

> Developers: what each of your customers cost you over a range, in one call — spend net of refunds, how many charges, and spend by kind. Customers with no charges in the range are left out (list them with `GET /customers`). Without `from`/`to` it is this month so far; days are UTC and a range covers at most 366 days. Call it from your own workspace: the `Thinnest-Workspace` header is refused. Any key may call this, a **read-only** key included.



## OpenAPI

````yaml /api-reference/openapi.json get /customers/usage
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
  /customers/usage:
    get:
      tags:
        - Usage
      summary: Get Customers Usage
      description: >-
        Developers: what each of your customers cost you over a range, in one
        call — spend net of refunds, how many charges, and spend by kind.
        Customers with no charges in the range are left out (list them with `GET
        /customers`). Without `from`/`to` it is this month so far; days are UTC
        and a range covers at most 366 days. Call it from your own workspace:
        the `Thinnest-Workspace` header is refused. Any key may call this, a
        **read-only** key included.
      operationId: getCustomersUsage
      parameters:
        - name: from
          in: query
          required: false
          description: >-
            First UTC day, YYYY-MM-DD. Needs `to`. Default: the 1st of this
            month.
          schema:
            type: string
            format: date
          example: '2026-09-01'
        - name: to
          in: query
          required: false
          description: 'Last UTC day, YYYY-MM-DD. Needs `from`. Default: today.'
          schema:
            type: string
            format: date
          example: '2026-09-30'
      responses:
        '200':
          description: Spend per customer.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UsageCustomers'
              example:
                timezone: UTC
                from: '2026-09-01'
                to: '2026-09-30'
                currency: INR
                totalMicro: 4318200000
                items:
                  - customer: org_3fKq9TzQ1mN8vB2xR7cLpA
                    name: Mehta Realty
                    externalId: crm-1042
                    state: active
                    spendMicro: 3120000000
                    entries: 812
                    byKind:
                      voice_call: 2410000000
                      reply: 710000000
                  - customer: org_7Lm2Qp4Rs8Tv1Wx3Yz5AbC
                    name: null
                    externalId: null
                    state: erased
                    spendMicro: 1198200000
                    entries: 233
                    byKind:
                      wa_message: 1198200000
        '400':
          description: The header was sent, or a bad range.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                e1:
                  summary: >-
                    Manage customers without the Thinnest-Workspace header: they
                    belong to your own workspace.
                  value:
                    error: >-
                      Manage customers without the Thinnest-Workspace header:
                      they belong to your own workspace.
                e2:
                  summary: >-
                    Use `from` and `to` (YYYY-MM-DD); without them, this month
                    so far.
                  value:
                    error: >-
                      Use `from` and `to` (YYYY-MM-DD); without them, this month
                      so far.
                e3:
                  summary: >-
                    Give both `from` and `to` as real dates, YYYY-MM-DD, or use
                    `days` instead.
                  value:
                    error: >-
                      Give both `from` and `to` as real dates, YYYY-MM-DD, or
                      use `days` instead.
                e4:
                  summary: '`to` is before `from`.'
                  value:
                    error: '`to` is before `from`.'
                e5:
                  summary: A range can cover at most 366 days.
                  value:
                    error: A range can cover at most 366 days.
                e6:
                  summary: '`from` is in the future.'
                  value:
                    error: '`from` is in the future.'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          description: The workspace no longer exists.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: Workspace not found.
        '409':
          description: A white-label reseller has clients, not API customers.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  This workspace resells the console under white label: its
                  workspaces are clients, managed in White label → Clients, not
                  API customers.
        '429':
          $ref: '#/components/responses/TooManyRequests'
components:
  schemas:
    UsageCustomers:
      type: object
      required:
        - timezone
        - from
        - to
        - currency
        - totalMicro
        - items
      properties:
        timezone:
          type: string
          description: Days are UTC, as Settings → Developer counts the month.
          enum:
            - UTC
        from:
          type: string
          description: First day counted.
          format: date
        to:
          type: string
          description: Last day counted (cut to today).
          format: date
        currency:
          type: string
          description: Your workspace's currency (INR when unset).
          enum:
            - INR
            - USD
        totalMicro:
          type: integer
          description: >-
            Spend across all customers in the range. Integer micro-units of
            `currency`: 1000000 is one rupee or one dollar.
        items:
          type: array
          description: One per customer with charges in the range, biggest spend first.
          items:
            $ref: '#/components/schemas/UsageCustomer'
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
    UsageCustomer:
      type: object
      required:
        - customer
        - name
        - externalId
        - state
        - spendMicro
        - entries
        - byKind
      properties:
        customer:
          type: string
          description: The customer workspace's id.
          example: org_3fKq9TzQ1mN8vB2xR7cLpA
        name:
          type:
            - string
            - 'null'
          description: Its name; `null` once erased.
        externalId:
          type:
            - string
            - 'null'
          description: Your own id for it, as set on `POST /customers`.
        state:
          type: string
          description: >-
            `active`, `archived` (awaiting erasure) or `erased` (gone; its
            charges kept).
          enum:
            - active
            - archived
            - erased
        spendMicro:
          type: integer
          description: >-
            Spend, net of refunds. Integer micro-units of `currency`: 1000000 is
            one rupee or one dollar.
        entries:
          type: integer
          description: How many ledger charges.
        byKind:
          type: object
          description: Spend by ledger kind (see `GET /wallet/ledger`), micro-units.
          additionalProperties:
            type: integer
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