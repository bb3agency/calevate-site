> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Delete Customer

> Deletes a customer: requests into it answer `410` from now on, every key made for it is revoked, its webhooks are switched off, its campaigns cancelled and its sequences and scheduled callbacks stopped (a call already in progress finishes). **30 days later it is erased** — every conversation, contact, recording and file — unless you restore it first. Refused while the customer still holds a rented phone number or a connected WhatsApp number: release those yourself first, because that cannot be undone. Deleting an already-deleted customer answers it as it is. Needs a **full** key.



## OpenAPI

````yaml /api-reference/openapi.json delete /customers/{id}
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
  /customers/{id}:
    parameters:
      - name: id
        in: path
        required: true
        description: The customer's `id` (`org_…`), as Create Customer answered.
        schema:
          type: string
        example: org_5b2f9c1e-8a4d-4f7b-9e3a-2c6d1f0a7b84
    delete:
      tags:
        - Customers
      summary: Delete Customer
      description: >-
        Deletes a customer: requests into it answer `410` from now on, every key
        made for it is revoked, its webhooks are switched off, its campaigns
        cancelled and its sequences and scheduled callbacks stopped (a call
        already in progress finishes). **30 days later it is erased** — every
        conversation, contact, recording and file — unless you restore it first.
        Refused while the customer still holds a rented phone number or a
        connected WhatsApp number: release those yourself first, because that
        cannot be undone. Deleting an already-deleted customer answers it as it
        is. Needs a **full** key.
      operationId: deleteCustomer
      parameters: []
      responses:
        '200':
          description: The customer, now deleted, with the date it will be erased.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Customer'
              example:
                id: org_5b2f9c1e-8a4d-4f7b-9e3a-2c6d1f0a7b84
                name: Sunrise Dental Clinic
                externalId: clinic-0042
                metadata:
                  city: Pune
                  tier: gold
                  seats: 3
                timezone: Asia/Kolkata
                allottedCallLines: 2
                archivedAt: '2026-10-06T10:05:41.203Z'
                eraseAfter: '2026-11-05T10:05:41.203Z'
                createdAt: '2026-10-02T06:14:22.418Z'
        '400':
          description: >-
            The request carried the `Thinnest-Workspace` header. Customers are
            managed from your own workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  Manage customers without the Thinnest-Workspace header: they
                  belong to your own workspace.
        '401':
          $ref: '#/components/responses/Unauthorized'
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: >-
            You have no customer with that id. Another developer's customer
            reads the same.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: Customer not found.
        '409':
          description: >-
            The customer still holds a rented phone number or a connected
            WhatsApp number (each is named), or your workspace is a white-label
            reseller.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  This customer still holds phone number +918041234567. Release
                  it first: that is permanent, so it is never done as a side
                  effect of deleting.
        '429':
          $ref: '#/components/responses/TooManyRequests'
components:
  schemas:
    Customer:
      type: object
      description: A workspace you created for one of your customers.
      required:
        - id
        - name
        - externalId
        - metadata
        - timezone
        - allottedCallLines
        - archivedAt
        - eraseAfter
        - createdAt
      properties:
        id:
          type: string
          description: >-
            The customer's id (`org_…`). Send it as `Thinnest-Workspace` to act
            inside this customer.
          example: org_5b2f9c1e-8a4d-4f7b-9e3a-2c6d1f0a7b84
        name:
          type: string
          maxLength: 120
          description: The customer's name.
          example: Sunrise Dental Clinic
        externalId:
          type:
            - string
            - 'null'
          description: >-
            Your own id for this customer, unique among your customers; null
            when you gave none.
          example: clinic-0042
        metadata:
          $ref: '#/components/schemas/CustomerMetadata'
        timezone:
          type: string
          description: >-
            The customer's IANA time zone; every date its console shows is in
            it.
          example: Asia/Kolkata
        allottedCallLines:
          type:
            - integer
            - 'null'
          minimum: 0
          description: >-
            How many of your call lines this customer may use at once; null for
            no cap.
          example: 2
        archivedAt:
          type:
            - string
            - 'null'
          format: date-time
          description: When the customer was deleted; null while it is live.
          example: null
        eraseAfter:
          type:
            - string
            - 'null'
          format: date-time
          description: >-
            When a deleted customer will be erased for good (30 days after
            deletion); null while it is live.
          example: null
        createdAt:
          type: string
          format: date-time
          description: When the customer was created.
          example: '2026-10-02T06:14:22.418Z'
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
    CustomerMetadata:
      type: object
      description: >-
        Your own flat key-value data about the customer: up to 50 keys of 1-40
        characters, each value a string (up to 500 characters), a number or a
        boolean. No nested objects or lists; 8 KB in all.
      maxProperties: 50
      propertyNames:
        minLength: 1
        maxLength: 40
      additionalProperties:
        oneOf:
          - type: string
            maxLength: 500
          - type: number
          - type: boolean
      example:
        city: Pune
        tier: gold
        seats: 3
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