> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# List Conversation Messages

> One conversation's messages, newest first: the customer's, your agent's, and replies a teammate sent from the inbox (`author: "teammate"`). Your team's internal notes are left out. Photos, voice notes, videos and documents a customer sent come back as links valid for **eight hours** — download what you need to keep.



## OpenAPI

````yaml /api-reference/openapi.json get /conversations/{id}/messages
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
  /conversations/{id}/messages:
    get:
      tags:
        - Conversations
      summary: List Conversation Messages
      description: >-
        One conversation's messages, newest first: the customer's, your agent's,
        and replies a teammate sent from the inbox (`author: "teammate"`). Your
        team's internal notes are left out. Photos, voice notes, videos and
        documents a customer sent come back as links valid for **eight hours** —
        download what you need to keep.
      operationId: listConversationMessages
      parameters:
        - name: id
          in: path
          required: true
          description: >-
            The conversation's id (`conv_…`), as the list and the
            `message.received` webhook give it.
          schema:
            type: string
          example: conv_8d41f2a7-3c6e-4b19-9f05-6a2e7c1d4b83
        - name: since
          in: query
          required: false
          description: ISO 8601 date and time. Keeps messages written after this moment.
          schema:
            type: string
            format: date-time
          example: '2026-10-06T09:00:00Z'
        - $ref: '#/components/parameters/Limit'
        - $ref: '#/components/parameters/Cursor'
        - $ref: '#/components/parameters/Workspace'
      responses:
        '200':
          description: A page of messages.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ConversationMessageList'
              example:
                items:
                  - id: msg_6f2a9d4c-1e8b-4c73-a5d0-3b9e7f2c8a16
                    author: agent
                    parts:
                      - type: text
                        text: >-
                          Sorry about that, Priya. I have raised a replacement
                          for order #10432 — it ships tomorrow.
                    createdAt: '2026-10-06T10:15:09.220Z'
                  - id: msg_0c3e7a9b-5d1f-4e82-b6a4-8f2d1c9e7b50
                    author: customer
                    parts:
                      - type: text
                        text: The box arrived damaged
                      - type: image
                        url: >-
                          https://storage.example.com/media/conv_8d41f2a7/photo.jpg?token=eyJhbGciOi
                        alt: ''
                    createdAt: '2026-10-06T10:15:01.482Z'
                nextCursor: null
        '400':
          description: '`since`, `limit` or `cursor` is not valid.'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: '`since` must be an ISO 8601 date and time.'
        '401':
          $ref: '#/components/responses/Unauthorized'
        '404':
          description: No such conversation in this workspace.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: Conversation was not found.
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
    ConversationMessageList:
      type: object
      required:
        - items
        - nextCursor
      properties:
        items:
          type: array
          items:
            $ref: '#/components/schemas/ConversationMessage'
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
    ConversationMessage:
      type: object
      required:
        - id
        - author
        - parts
        - createdAt
      properties:
        id:
          type: string
          description: >-
            The message's id (`msg_…`) — the `messageId` a `message.received`
            delivery carries, so you can skip ones you already handled.
          example: msg_0c3e7a9b-5d1f-4e82-b6a4-8f2d1c9e7b50
        author:
          type: string
          enum:
            - customer
            - agent
            - teammate
          description: >-
            Who wrote it: the customer, your agent (ours or your own platform's
            replies), or a teammate from the inbox.
        parts:
          type: array
          description: The message's content, in order. Most messages are one `text` part.
          items:
            $ref: '#/components/schemas/ConversationMessagePart'
        createdAt:
          type: string
          format: date-time
          description: When it was written.
    ConversationMessagePart:
      description: One piece of a message, by `type`.
      oneOf:
        - $ref: '#/components/schemas/ConversationTextPart'
        - $ref: '#/components/schemas/ConversationImagePart'
        - $ref: '#/components/schemas/ConversationAudioPart'
        - $ref: '#/components/schemas/ConversationVideoPart'
        - $ref: '#/components/schemas/ConversationFilePart'
        - $ref: '#/components/schemas/ConversationLinkPart'
        - $ref: '#/components/schemas/ConversationCardPart'
        - $ref: '#/components/schemas/ConversationCarouselPart'
        - $ref: '#/components/schemas/ConversationChoicesPart'
        - $ref: '#/components/schemas/ConversationSlotsPart'
        - $ref: '#/components/schemas/ConversationFormPart'
        - $ref: '#/components/schemas/ConversationProductsPart'
      discriminator:
        propertyName: type
        mapping:
          text: '#/components/schemas/ConversationTextPart'
          image: '#/components/schemas/ConversationImagePart'
          audio: '#/components/schemas/ConversationAudioPart'
          video: '#/components/schemas/ConversationVideoPart'
          file: '#/components/schemas/ConversationFilePart'
          link: '#/components/schemas/ConversationLinkPart'
          card: '#/components/schemas/ConversationCardPart'
          carousel: '#/components/schemas/ConversationCarouselPart'
          choices: '#/components/schemas/ConversationChoicesPart'
          slots: '#/components/schemas/ConversationSlotsPart'
          form: '#/components/schemas/ConversationFormPart'
          products: '#/components/schemas/ConversationProductsPart'
    ConversationTextPart:
      type: object
      title: Text
      required:
        - type
        - text
      properties:
        type:
          type: string
          const: text
        text:
          type: string
          description: The words.
    ConversationImagePart:
      type: object
      title: Image
      required:
        - type
        - url
        - alt
      properties:
        type:
          type: string
          const: image
        url:
          type: string
          format: uri
          description: >-
            The picture. A file a customer sent is a signed link valid for eight
            hours.
        alt:
          type: string
          description: A description or caption. Often empty for a customer's photo.
    ConversationAudioPart:
      type: object
      title: Audio
      required:
        - type
        - url
      properties:
        type:
          type: string
          const: audio
        url:
          type: string
          format: uri
          description: >-
            The voice note or recording. A signed link valid for eight hours
            when stored by us.
        transcript:
          type: string
          description: What was said, once transcribed.
        durationSeconds:
          type: number
          description: Length in seconds, when known.
    ConversationVideoPart:
      type: object
      title: Video
      required:
        - type
        - url
        - alt
      properties:
        type:
          type: string
          const: video
        url:
          type: string
          format: uri
          description: The video. A signed link valid for eight hours when stored by us.
        alt:
          type: string
          description: What is in it, or its caption.
        posterUrl:
          type: string
          format: uri
          description: A still shown before playback, when there is one.
        mimeType:
          type: string
          description: e.g. `video/mp4`.
        durationSeconds:
          type: number
          description: Length in seconds, when known.
        sizeBytes:
          type: integer
          description: Size in bytes, when known.
    ConversationFilePart:
      type: object
      title: File
      required:
        - type
        - url
        - name
      properties:
        type:
          type: string
          const: file
        url:
          type: string
          format: uri
          description: The document. A signed link valid for eight hours when stored by us.
        name:
          type: string
          description: The file's name, e.g. `invoice-10432.pdf`.
        mimeType:
          type: string
          description: e.g. `application/pdf`.
        sizeBytes:
          type: integer
          description: Size in bytes, when known.
    ConversationLinkPart:
      type: object
      title: Link button
      required:
        - type
        - text
        - url
        - label
      properties:
        type:
          type: string
          const: link
        text:
          type: string
          description: The message the button sits under.
        url:
          type: string
          format: uri
          description: Where the button goes.
        label:
          type: string
          description: The button's words, e.g. "Book a table".
    ConversationCardPart:
      type: object
      title: Card
      required:
        - type
        - title
      properties:
        type:
          type: string
          const: card
        title:
          type: string
          description: The card's heading.
        subtitle:
          type: string
          description: A line under the heading.
        imageUrl:
          type: string
          format: uri
          description: The card's picture.
        actions:
          type: array
          description: Buttons on the card.
          items:
            $ref: '#/components/schemas/ConversationChoiceOption'
    ConversationCarouselPart:
      type: object
      title: Carousel
      required:
        - type
        - items
      properties:
        type:
          type: string
          const: carousel
        items:
          type: array
          description: The cards, in order. Each has the fields of a `card` part.
          items:
            type: object
            required:
              - title
            properties:
              type:
                type: string
                const: card
              title:
                type: string
                description: The card's heading.
              subtitle:
                type: string
                description: A line under the heading.
              imageUrl:
                type: string
                format: uri
                description: The card's picture.
              actions:
                type: array
                description: Buttons on the card.
                items:
                  $ref: '#/components/schemas/ConversationChoiceOption'
    ConversationChoicesPart:
      type: object
      title: Choices
      required:
        - type
        - prompt
        - options
      properties:
        type:
          type: string
          const: choices
        prompt:
          type: string
          description: The question.
        options:
          type: array
          description: The answers offered.
          items:
            $ref: '#/components/schemas/ConversationChoiceOption'
    ConversationSlotsPart:
      type: object
      title: Time slots
      required:
        - type
        - prompt
        - slots
      properties:
        type:
          type: string
          const: slots
        prompt:
          type: string
          description: The question.
        slots:
          type: array
          description: The times offered, as ISO 8601 instants.
          items:
            type: string
            format: date-time
    ConversationFormPart:
      type: object
      title: Inline form
      required:
        - type
        - prompt
        - fields
      properties:
        type:
          type: string
          const: form
        prompt:
          type: string
          description: What the form asks for.
        fields:
          type: array
          description: The boxes to fill in.
          items:
            type: object
            required:
              - name
              - label
              - kind
              - required
            properties:
              name:
                type: string
                description: The key the answer comes back under.
              label:
                type: string
                description: What the customer reads.
              kind:
                type: string
                enum:
                  - text
                  - email
                  - tel
                description: The kind of box.
              required:
                type: boolean
                description: Whether it must be filled in.
    ConversationProductsPart:
      type: object
      title: Products
      required:
        - type
        - caption
        - catalogId
        - productIds
      properties:
        type:
          type: string
          const: products
        caption:
          type: string
          description: The words around the products.
        catalogId:
          type: string
          description: The WhatsApp catalogue's id, digits only.
        productIds:
          type: array
          description: >-
            Your own SKUs. Empty opens the whole catalogue, one shows that
            product, several show a picker.
          items:
            type: string
        sectionTitle:
          type: string
          description: The picker's heading, when several products are named.
    ConversationChoiceOption:
      type: object
      required:
        - id
        - label
      properties:
        id:
          type: string
          description: Stable identifier sent back when chosen.
        label:
          type: string
          description: What the customer sees.
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