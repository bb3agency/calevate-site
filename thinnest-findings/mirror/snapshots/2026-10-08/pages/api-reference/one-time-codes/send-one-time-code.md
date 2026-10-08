> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Send One-Time Code

> Sends a code you generated to a WhatsApp number, using your approved authentication template — the code goes into the message **and** the copy-code button. We do not generate, store, expire or check the code; that stays yours. One number may be sent at most 5 codes in 10 minutes, and the workspace at most 120 sends a minute (codes keep the top of the budget it shares with Send Message). Each code is charged at WhatsApp's authentication rate, which is far higher for numbers abroad. Needs a **full** key.



## OpenAPI

````yaml /api-reference/openapi.json post /codes
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
      when one of your keys fails. The switch is per workspace, and each agent
      follows it by default: set an agent's `byok` to `"off"` (Create Agent,
      Update Agent) and that one agent runs on our voices and models at our
      normal pricing — chat replies billed normally, the voice-only model limit
      not applied — while your other agents stay on your keys. A call is priced
      and run on one stack: the agent's setting is read once when the call or
      reply starts.
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
  /codes:
    post:
      tags:
        - One-time codes
      summary: Send One-Time Code
      description: >-
        Sends a code you generated to a WhatsApp number, using your approved
        authentication template — the code goes into the message **and** the
        copy-code button. We do not generate, store, expire or check the code;
        that stays yours. One number may be sent at most 5 codes in 10 minutes,
        and the workspace at most 120 sends a minute (codes keep the top of the
        budget it shares with Send Message). Each code is charged at WhatsApp's
        authentication rate, which is far higher for numbers abroad. Needs a
        **full** key.
      operationId: sendCode
      parameters:
        - $ref: '#/components/parameters/IdempotencyKey'
        - $ref: '#/components/parameters/Workspace'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/CodeSendRequest'
            example:
              to: +91 98123 45678
              code: '394812'
      responses:
        '200':
          description: >-
            WhatsApp accepted the code. A replay of an `Idempotency-Key` returns
            the first answer, whatever it was, with an `Idempotent-Replayed:
            true` header.
          headers:
            Idempotent-Replayed:
              description: >-
                `true` when this is the stored answer to an earlier request with
                the same `Idempotency-Key`.
              schema:
                type: string
                enum:
                  - 'true'
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CodeSent'
              example:
                sent: true
                to: '919812345678'
                template: login_code
                language: en
                messageRef: wamid.HBgMOTE5ODEyMzQ1Njc4FQIAERgSNEQ3QTlFMkI1QzFGOEQ2MEEA
        '400':
          description: >-
            The body is not JSON, `to` or `code` is missing, the code is over 16
            characters, or the number cannot be read.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: That does not look like a code — 16 characters at most.
                code: validation_failed
        '401':
          $ref: '#/components/responses/Unauthorized'
        '402':
          description: >-
            The Free plan's WhatsApp messages are used up. Switching to
            pay-as-you-go lifts it.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: >-
                  The Free plan includes 200 WhatsApp messages, and they are
                  used. Switch to Pay as you go — there is no monthly fee — to
                  keep sending.
                code: free_allowance_used
        '403':
          $ref: '#/components/responses/Forbidden'
        '404':
          description: >-
            No approved authentication template (of that name and in that
            language, when you named them). When you sent a `language` and
            templates are approved in others, the sentence lists those
            languages; otherwise create one with Create Code Template and submit
            it for review.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              examples:
                none:
                  summary: None approved yet
                  value:
                    error: >-
                      No approved authentication template yet. Create one under
                      One-time codes and submit it for review.
                    code: code_template_not_found
                language:
                  summary: Approved, but in other languages
                  value:
                    error: >-
                      No approved authentication template in "ta". Approved in:
                      en, hi.
                    code: code_template_not_found
        '409':
          description: >-
            More than one approved code template matches — the answer lists them
            in `templates`; name one with `template`, or with `language` when
            one name is approved in several languages. Also: WhatsApp is not
            connected (`whatsapp_not_connected`), sending is restricted on the
            number (`whatsapp_blocked`), or a request with the same
            `Idempotency-Key` is still in flight (`idempotency_in_progress`).
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/CodeAmbiguous'
              example:
                error: >-
                  "login_code" is approved in more than one language — say which
                  with `language`.
                code: code_template_ambiguous
                templates:
                  - template: login_code
                    language: en
                  - template: login_code
                    language: hi
        '410':
          $ref: '#/components/responses/WorkspaceDeleted'
        '429':
          description: >-
            Over 120 sends a minute for the workspace (`code: rate_limit_codes`,
            `Retry-After: 60`), or 5 codes to this number in the last 10 minutes
            (`code: rate_limit_code_recipient`, `Retry-After: 600`). `limit`
            names which. The `Idempotency-Key` is released, so a later retry
            with it is a real retry.
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
                error: >-
                  That number has already been sent 5 codes in the last 10
                  minutes.
                code: rate_limit_code_recipient
                limit:
                  name: code_recipient
                  max: 5
                  windowSeconds: 600
        '502':
          description: >-
            WhatsApp refused the message, in its own words. Usually a bad moment
            — safe to retry.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: (#131000) Something went wrong
                code: send_failed
        '503':
          description: WhatsApp sending is not available right now. Retry later.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Error'
              example:
                error: WhatsApp is not configured on this deployment.
                code: whatsapp_not_configured
components:
  parameters:
    IdempotencyKey:
      name: Idempotency-Key
      in: header
      required: false
      description: >-
        Any unique string. A retry with the same key within 24 hours returns the
        first request's answer instead of acting twice.
      schema:
        type: string
        maxLength: 255
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
    CodeSendRequest:
      type: object
      required:
        - to
        - code
      properties:
        to:
          type: string
          description: >-
            The number to send the code to. Include the `+` and the country code
            (a leading `00` works too). Without a `+`, a number of ten digits or
            fewer — or one starting with `0` — is read as an Indian number and
            `91` is added.
          example: +91 98123 45678
        code:
          type: string
          minLength: 1
          maxLength: 16
          description: The code you generated, 16 characters at most after trimming.
          example: '394812'
        template:
          type: string
          description: >-
            Which approved authentication template, by name. Needed only when
            you have more than one.
          example: login_code
        language:
          type: string
          description: >-
            Which approved language version, exactly as approved — `en`, `hi`.
            Needed only when one template name is approved in several languages.
          example: en
        idempotencyKey:
          type: string
          description: >-
            Same as the `Idempotency-Key` header, for clients that cannot set
            headers. The header wins when both are sent.
    CodeSent:
      type: object
      required:
        - sent
        - to
        - template
        - language
        - messageRef
      properties:
        sent:
          type: boolean
          const: true
          description: WhatsApp accepted the code.
        to:
          type: string
          description: The number it went to, digits only with the country code.
        template:
          type: string
          description: The template it was sent with.
        language:
          type: string
          description: The language version it was sent in.
        messageRef:
          type:
            - string
            - 'null'
          description: WhatsApp's receipt for the message.
    Error:
      type: object
      required:
        - error
        - code
      properties:
        error:
          type: string
          description: What went wrong, in a sentence you can show a person.
        code:
          type: string
          enum:
            - unauthorized
            - key_scope_read
            - key_scope_build
            - workspace_not_found
            - workspace_deleted
            - workspace_not_developer
            - workspace_header_forbidden
            - rate_limit_resources
            - rate_limit_family
            - rate_limit_calls
            - rate_limit_messages
            - rate_limit_codes
            - rate_limit_code_recipient
            - concurrent_calls
            - number_daily_limit
            - rate_limited
            - opted_out
            - do_not_call
            - stop_list_unknown
            - insufficient_balance
            - outside_calling_hours
            - number_never_callable
            - call_in_progress
            - call_already_scheduled
            - calling_not_set_up
            - carrier_unavailable
            - agent_not_found
            - agent_ambiguous
            - from_number_invalid
            - invalid_number
            - number_required
            - number_claimed_elsewhere
            - needs_own_carrier_keys
            - template_not_found
            - template_not_approved
            - template_language_missing
            - template_unsendable
            - code_template_not_found
            - code_template_ambiguous
            - whatsapp_not_connected
            - whatsapp_blocked
            - whatsapp_not_configured
            - free_allowance_used
            - send_failed
            - plan_required
            - plan_limit
            - payment_required
            - idempotency_in_progress
            - validation_failed
            - forbidden
            - not_found
            - conflict
            - gone
            - unprocessable
            - internal_error
            - service_unavailable
          description: >-
            A stable machine-readable code. Two refusals that share a status are
            told apart by it (a `403` for an opted-out customer, for the
            do-not-call list and for a key that is not a full key). See the
            table in the API reference under Errors.
        limit:
          type: object
          description: >-
            On a `429` that hit one of our limits: which one and how big it is.
            `perMinute` for a per-minute limit; `max` (and `windowSeconds`) for
            the others.
          required:
            - name
          properties:
            name:
              type: string
              description: >-
                Which limit: `resources`, `family`, `calls`, `messages`,
                `codes`, `code_recipient`, `concurrent_calls` or `number_daily`.
            perMinute:
              type: integer
              description: Requests allowed a minute.
            max:
              type: integer
              description: The most allowed, for a limit that is not per minute.
            windowSeconds:
              type: integer
              description: The window `max` is counted over, when it has one.
      example:
        error: That agent was not found.
        code: not_found
      description: >-
        Every error body. Branch on `code`, never on the sentence in `error`:
        the sentence may be reworded, the code does not change.
    CodeAmbiguous:
      type: object
      required:
        - error
        - code
      properties:
        error:
          type: string
          description: What went wrong, in a sentence you can show a person.
        code:
          type: string
          const: code_template_ambiguous
          description: Always `code_template_ambiguous`.
        templates:
          type: array
          description: >-
            When more than one approved template matched: the candidates, to
            choose from with `template` and `language`.
          items:
            type: object
            required:
              - template
              - language
            properties:
              template:
                type: string
                description: The template's name.
              language:
                type: string
                description: Its language.
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
            code: unauthorized
    Forbidden:
      description: >-
        The key's access level (read-only or build) does not allow this request,
        the plan does not include it, or a customer's key named another
        workspace in `Thinnest-Workspace`. `code` says which: `key_scope_read`,
        `key_scope_build`, `workspace_header_forbidden`, or `forbidden`.
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
                code: key_scope_read
            buildKey:
              summary: >-
                A build key tried to message customers, send codes or place
                calls
              value:
                error: >-
                  This API key is a build key: it can set up agents, actions,
                  contacts and webhooks, but not message customers, send codes
                  or place calls. Use a full key for that.
                code: key_scope_build
            customerKey:
              summary: A customer's key named another workspace
              value:
                error: >-
                  This key belongs to one customer workspace and cannot act as
                  another.
                code: workspace_header_forbidden
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
            code: workspace_deleted
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