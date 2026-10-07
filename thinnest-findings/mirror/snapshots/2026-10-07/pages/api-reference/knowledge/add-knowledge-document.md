> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Add Knowledge Document

> Adds a web page (`url`) or pasted `text` to what the agent knows. A page is fetched and indexed before this answers, so a slow site is a slow request; `passages` says how much was indexed. A page that cannot be read is answered `422` with the reason and the `failed` document it left behind, which you can delete. Files are uploaded in the console. A **build** key may do this.



## OpenAPI

````yaml /api-reference/openapi.json post /agents/{id}/knowledge
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
  /agents/{id}/knowledge:
    parameters:
      - name: id
        in: path
        required: true
        description: The agent's id (`ag_…`).
        schema:
          type: string
        example: ag_5c4a5f93-2b1e-4d7a-9f60-8e2d1c3b4a71
    post:
      tags:
        - Knowledge
      summary: Add Knowledge Document
      description: >-
        Adds a web page (`url`) or pasted `text` to what the agent knows. A page
        is fetched and indexed before this answers, so a slow site is a slow
        request; `passages` says how much was indexed. A page that cannot be
        read is answered `422` with the reason and the `failed` document it left
        behind, which you can delete. Files are uploaded in the console. A
        **build** key may do this.
      operationId: addKnowledgeDocument
      parameters:
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/KnowledgeDocumentRequest'
            examples:
              text:
                summary: Pasted text
                value:
                  title: Sky Towers price list
                  text: >-
                    A 2 BHK at Sky Towers starts at 82 lakh. A 3 BHK starts at
                    1.1 crore. Possession is December 2027.
              url:
                summary: A web page
                value:
                  url: https://skylinehomes.example/sky-towers/prices
      responses:
        '201':
          description: The document, indexed and ready to cite.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/KnowledgeDocumentAdded'
              example:
                id: doc_f7413c2a-9d0e-4b6f-8a21-3e5c7d9b1f04
                title: Sky Towers price list
                type: text
                source: pasted
                status: ready
                error: null
                createdAt: '2026-10-06T09:41:58.307Z'
                passages: 3
        '400':
          description: >-
            Neither or both of `url` and `text`, `text` too long, or `url` not
            http(s).
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                neither:
                  summary: Nothing to add
                  value:
                    error: >-
                      Send a `url` to fetch, or `text` to index (with an
                      optional `title`).
                both:
                  summary: Both sent
                  value:
                    error: Send either `url` or `text`, not both.
                long:
                  summary: Text too long
                  value:
                    error: >-
                      `text` is too long to add at once — 200000 characters at
                      most.
                scheme:
                  summary: Not a web address
                  value:
                    error: '`url` must start with http:// or https://.'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: No such agent in your workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That agent was not found.
        '422':
          description: >-
            The page or text could not be indexed. `document` is the `failed`
            document left on the agent, when one was written — delete it or fix
            the page and add it again.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/KnowledgeDocumentFailed'
              example:
                error: >-
                  No readable text found — the page may require JavaScript or a
                  login.
                document:
                  id: doc_2b9e7d14-6c3a-4f81-b0d5-9a7e1c4f3b62
                  title: https://skylinehomes.example/faq
                  type: url
                  source: https://skylinehomes.example/faq
                  status: failed
                  error: >-
                    No readable text found — the page may require JavaScript or
                    a login.
                  createdAt: '2026-10-06T09:44:12.880Z'
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
    KnowledgeDocumentRequest:
      type: object
      description: Send `url`, or `text` with an optional `title` — not both.
      properties:
        url:
          type: string
          format: uri
          description: >-
            A web page to fetch and index. Must start with `http://` or
            `https://`.
        text:
          type: string
          maxLength: 200000
          description: Text to index, up to 200,000 characters. Trimmed.
        title:
          type: string
          maxLength: 200
          description: >-
            A title for `text`; cut to 200 characters. Left out, it is `Pasted
            text`. Ignored with `url`, whose title comes from the page.
    KnowledgeDocumentAdded:
      type: object
      description: The document just added, with how many passages were indexed from it.
      required:
        - id
        - title
        - type
        - source
        - status
        - error
        - createdAt
        - passages
      properties:
        id:
          type: string
          description: The document's id.
        title:
          type: string
          description: 'Its title: the one you sent, the page''s own, or `Pasted text`.'
        type:
          type: string
          enum:
            - url
            - text
          description: Where it came from.
        source:
          type: string
          description: The address for a `url`, `pasted` for `text`.
        status:
          type: string
          enum:
            - ready
          description: Always `ready` on success.
        error:
          type: 'null'
          description: Always null on success.
        createdAt:
          type: string
          format: date-time
          description: When it was added.
        passages:
          type: integer
          minimum: 1
          description: How many passages were indexed.
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
    KnowledgeDocumentFailed:
      type: object
      required:
        - error
      properties:
        error:
          type: string
          description: Why it could not be indexed, in the console's words.
        document:
          $ref: '#/components/schemas/KnowledgeDocument'
    KnowledgeDocument:
      type: object
      description: One document an agent knows.
      required:
        - id
        - title
        - type
        - source
        - status
        - error
        - createdAt
      properties:
        id:
          type: string
          description: The document's id.
          example: doc_f7413c2a-9d0e-4b6f-8a21-3e5c7d9b1f04
        title:
          type: string
          description: >-
            Its title: the one you sent, the page's own, or the address while a
            page has not been read.
        type:
          type: string
          enum:
            - url
            - text
            - file
          description: Where it came from.
        source:
          type: string
          description: >-
            The address for a `url`, `pasted` for `text`, the file name for a
            `file`.
        status:
          type: string
          enum:
            - pending
            - indexing
            - ready
            - failed
          description: >-
            `ready` once the agent can cite it; `failed` with `error` when it
            could not be read.
        error:
          type:
            - string
            - 'null'
          description: >-
            Why it failed, e.g. the page needs JavaScript or answered 403; null
            otherwise.
        createdAt:
          type: string
          format: date-time
          description: When it was added.
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