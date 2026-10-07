> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Connect Tool Server

> Connect an MCP tool server that takes a token (or none). It is asked for its tools at once and every tool arrives **off** — switch each on with `PATCH …/tools/{toolId}`. A server that cannot be reached is still saved and answers `201` with `status: "failed"` and the reason in `message`, so you can fix it and sync. A server that signs in through a browser must be connected in the console. A **build** key may do this.



## OpenAPI

````yaml /api-reference/openapi.json post /agents/{id}/mcp-servers
openapi: 3.1.0
info:
  title: API
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
      when one of your keys fails.
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
  /agents/{id}/mcp-servers:
    parameters:
      - $ref: '#/components/parameters/ToolsAgentIdParam'
    post:
      tags:
        - Tools
      summary: Connect Tool Server
      description: >-
        Connect an MCP tool server that takes a token (or none). It is asked for
        its tools at once and every tool arrives **off** — switch each on with
        `PATCH …/tools/{toolId}`. A server that cannot be reached is still saved
        and answers `201` with `status: "failed"` and the reason in `message`,
        so you can fix it and sync. A server that signs in through a browser
        must be connected in the console. A **build** key may do this.
      operationId: connectToolServer
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CreateMcpServerRequest'
            example:
              name: Inventory
              url: https://mcp.urbanloom.in/mcp
              transport: http
              authHeaderName: Authorization
              secret: Bearer ul_mcp_4Rt9…
      responses:
        '201':
          description: Saved — check `status` to see whether discovery worked.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/McpServerWithMessage'
              example:
                id: mcp_5e1d2c7a-8b94-4f06-a3d1-2c9e7b5f0a18
                name: Inventory
                url: https://mcp.urbanloom.in/mcp
                transport: http
                signIn: token
                kind: server
                authHeaderName: Authorization
                hasSecret: true
                status: connected
                lastError: null
                lastSyncedAt: '2026-10-06T10:22:31.402Z'
                tools:
                  - id: tool_a2c47e19-3b5d-4f60-8e91-7d0b2c6f4a35
                    name: check_stock
                    description: Stock on hand for a product SKU, by warehouse.
                    enabled: false
                  - id: tool_c9e03b72-61f4-4a8d-b257-0e4d9a1c3f86
                    name: find_order
                    description: An order's status and courier tracking by order number.
                    enabled: false
                  - id: tool_f1b8d6a4-2e7c-4935-a0d1-6c3e9b5f7a20
                    name: list_collections
                    description: The store's current collections.
                    enabled: false
                createdAt: '2026-10-06T10:22:29.918Z'
                message: Found 3 tools. All start off.
        '400':
          description: A field is wrong, or the server needs a browser sign-in.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                required:
                  summary: Missing
                  value:
                    error: '`name` and `url` are required.'
                https:
                  summary: Not https
                  value:
                    error: The address must start with https://.
                private:
                  summary: Private address
                  value:
                    error: That address is not reachable from our servers.
                header:
                  summary: Secret without header
                  value:
                    error: Name the header the token should be sent in.
                browser:
                  summary: Browser sign-in
                  value:
                    error: >-
                      A server that signs in through a browser has to be
                      connected in the console. Connect it there, then manage
                      its tools here.
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
        '410':
          $ref: '#/components/responses/WorkspaceDeleted'
        '429':
          $ref: '#/components/responses/TooManyRequests'
        '503':
          description: A secret was sent and this deployment cannot store credentials.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: This deployment cannot store credentials yet.
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
    CreateMcpServerRequest:
      type: object
      required:
        - name
        - url
      properties:
        name:
          type: string
          description: Your name for it, 2 to 200 characters.
          minLength: 2
          maxLength: 200
        url:
          type: string
          description: >-
            Its `https://` address. It must be publicly reachable: private and
            internal addresses are refused.
          format: uri
          maxLength: 2000
        transport:
          type: string
          description: '`http` (streamable HTTP) or `sse`.'
          enum:
            - http
            - sse
          default: http
        authHeaderName:
          type: string
          description: >-
            The header to send the token in, e.g. `Authorization`. Required when
            `secret` is sent.
          maxLength: 200
        secret:
          type: string
          description: >-
            The header's value, e.g. `Bearer …`. **Write-only:** sealed on
            arrival; responses say only `hasSecret`.
          maxLength: 8000
    McpServerWithMessage:
      allOf:
        - $ref: '#/components/schemas/McpServer'
        - type: object
          required:
            - message
          properties:
            message:
              type:
                - string
                - 'null'
              description: >-
                What happened — how many tools were found, or why it could not
                be reached.
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
    McpServer:
      type: object
      required:
        - id
        - name
        - url
        - transport
        - signIn
        - kind
        - authHeaderName
        - hasSecret
        - status
        - lastError
        - lastSyncedAt
        - tools
        - createdAt
      properties:
        id:
          type: string
          description: The server's id, `mcp_…`.
          example: mcp_5e1d2c7a-8b94-4f06-a3d1-2c9e7b5f0a18
        name:
          type: string
          description: Your name for it.
        url:
          type: string
          description: Its `https://` address.
        transport:
          type: string
          description: How it is spoken to.
          enum:
            - http
            - sse
        signIn:
          type: string
          description: >-
            `token` for a server reached with a header you sent; `browser` for
            one signed in through the console.
          enum:
            - token
            - browser
        kind:
          type: string
          description: >-
            `server` for a tool server; `store` for a store connection made in
            the console, whose tools are a fixed list.
          enum:
            - server
            - store
        authHeaderName:
          type:
            - string
            - 'null'
          description: The header the token is sent in.
        hasSecret:
          type: boolean
          description: Whether a token is held. The token itself is never returned.
        status:
          type: string
          description: >-
            `connected` once it answered with its tools; `failed` when it could
            not be reached (see `lastError`); `pending` before the first answer.
        lastError:
          type:
            - string
            - 'null'
          description: Why the last attempt failed.
        lastSyncedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When it last listed its tools.
        tools:
          type: array
          description: What it offers, by name.
          items:
            $ref: '#/components/schemas/McpTool'
        createdAt:
          type: string
          description: When it was connected.
          format: date-time
    McpTool:
      type: object
      required:
        - id
        - name
        - description
        - enabled
      properties:
        id:
          type: string
          description: The tool's id, `tool_…`.
          example: tool_c9e03b72-61f4-4a8d-b257-0e4d9a1c3f86
        name:
          type: string
          description: The tool's name, as the server lists it.
        description:
          type: string
          description: The server's own description of it; empty when it gave none.
        enabled:
          type: boolean
          description: Whether the agent may call it. Every tool arrives off.
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
    Forbidden:
      description: >-
        The key's access level (read-only or build) does not allow this request,
        the plan does not include it, or a customer's key named another
        workspace in `Thinnest-Workspace`.
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
            buildKey:
              summary: >-
                A build key tried to message customers, send codes or place
                calls
              value:
                error: >-
                  This API key is a build key: it can set up agents, actions,
                  contacts and webhooks, but not message customers, send codes
                  or place calls. Use a full key for that.
            customerKey:
              summary: A customer's key named another workspace
              value:
                error: >-
                  This key belongs to one customer workspace and cannot act as
                  another.
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