> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Place a call

> POST /api/v1/calls — your agent rings a customer, says why, and reports back what it learned.

```http theme={null}
POST /api/v1/calls
Authorization: Bearer ta_live_…
Content-Type: application/json
Idempotency-Key: lead-LSQ-42
```

```json theme={null}
{
  "to": "919876543210",
  "purpose": "I'm calling from Skyline Homes about your enquiry for Sky Towers.",
  "name": "Asha Rao",
  "source": "99acres enquiry form",
  "reference": "LSQ-42",
  "variables": { "lead_name": "Asha", "project": "Sky Towers", "budget_asked": "2BHK" },
  "callingHours": { "start": "10:00", "end": "19:00", "days": ["mon", "tue", "wed", "thu", "fri", "sat"] },
  "extract": [
    { "name": "budget", "type": "number", "description": "Budget in rupees" },
    { "name": "interest", "choices": ["Hot", "Warm", "Cold"] },
    { "name": "site_visit", "type": "boolean" }
  ],
  "summary": true,
  "metadata": { "deal_id": "D-19", "owner": "Ravi" },
  "retry": { "count": 2, "noAnswerMinutes": 60, "busyMinutes": 15 },
  "from": "918045678901",
  "overrides": { "voice": "priya", "maxCallSeconds": 300 }
}
```

```json theme={null}
{
  "id": "out_9f2c1a44-...",
  "to": "919876543210",
  "from": "918045678901",
  "status": "ringing",
  "reference": "LSQ-42"
}
```

The agent dials, and the moment the customer picks up it says your `purpose` and
then holds a normal conversation — same knowledge, same instructions, same
memory of that customer as every other channel. When the call ends you get a
summary, the fields you asked for, the transcript and a recording link — see
[Get a call's results](/api-reference/get-call).

Only `to` and `purpose` are required. Everything else is how a CRM tells us what
it knows about the lead and what it wants back.

## Body

<ParamField body="to" type="string" required>
  The customer's number. E.164, with or without the `+`; spaces are fine.

  Normalised the same way the contact importer does, so `+91 98765 43210` and
  `919876543210` reach the same customer rather than making a second one.
</ParamField>

<ParamField body="purpose" type="string" required>
  Why you are calling, in your own words. **This is spoken aloud** as the first
  thing the customer hears.

  Maximum 300 characters. Write it as you would say it: *"I'm calling from
  Skyline Homes about your enquiry for Sky Towers"*, not *"lead follow-up"*.
</ParamField>

<ParamField body="agent" type="string">
  Which agent is calling — its name or id.

  Only needed when more than one agent in your workspace answers the phone.
</ParamField>

<ParamField body="name" type="string">
  The lead's name, up to 120 characters. If the number is not a contact yet, it
  becomes one with this name. An existing contact's name is never overwritten.
</ParamField>

<ParamField body="source" type="string">
  Where the lead came from — *"99acres enquiry form"*. Up to 120 characters,
  recorded on the contact so you can always say why you had the number.
</ParamField>

<ParamField body="reference" type="string">
  Your own id for this lead, up to 200 characters. Never interpreted — it comes
  back in the response, in [`GET /api/v1/calls/{id}`](/api-reference/get-call),
  and in both call webhooks, so you can match results to the right record.
</ParamField>

<ParamField body="variables" type="object">
  Values your agent's instructions can use as `{{name}}` — the lead's name, the
  project they asked about, their budget. Up to 20. Names are lower-cased with
  spaces turned into `_`, exactly as a calling-campaign upload does, so
  `"Lead Name"` is `{{lead_name}}`. Values are cut to 150 characters.
</ParamField>

<ParamField body="callingHours" type="object">
  When this person may be rung, **in their own time**. All parts are optional.

  * `start`, `end` — `"HH:MM"`. Must sit inside **09:00–21:00**, the legal
    window every call keeps anyway. Asking for 08:00 is refused, not moved.
  * `days` — `["mon", "tue", …]`. Leave it out for every day.
  * `timezone` — used only for a number whose country we cannot place. An Indian
    number is always read in India's time, whatever you send.

  Leave the whole object out and the call may be placed any day, 9am to 9pm.
</ParamField>

<ParamField body="ifOutsideHours" type="string" default="schedule">
  What to do when it is outside those hours right now.

  * `schedule` — queue the call for the minute the hours next open. You get a
    `202` with `status: "scheduled"` and `scheduledFor`.
  * `refuse` — answer `409` with `nextOpening`, and do nothing.
</ParamField>

<ParamField body="extract" type="object[]">
  The details you want filled from the call, up to 30. Each is:

  * `name` — letters, digits and `_`, starting with a letter. It comes back
    exactly as you sent it, so it can be your CRM's own field name.
  * `type` — `text` (default), `number`, `integer`, `boolean` or `date`. A value
    that does not fit is **left out** rather than sent wrong: a `number` is a
    number (*"80 lakh"* arrives as `8000000`), a `boolean` is `true` or `false`,
    a `date` is `YYYY-MM-DD`.
  * `description` — what the field means, up to 200 characters. Worth writing.
  * `choices` — for `text` only: the answer must be one of these, in your
    spelling.

  Leave it out and the agent's own **collect details** fields are used, if it
  has any.
</ParamField>

<ParamField body="summary" type="boolean">
  `true` writes two or three sentences about the call, `false` skips it. Leave
  it out to follow the agent's own **Summarise calls** switch.
</ParamField>

<ParamField body="metadata" type="object">
  Your own data, returned **exactly as sent** on every response, report and
  webhook for this call — deal ids, owner, campaign code. Up to 20 keys, 4,000
  characters in all. Values must be strings, numbers, `true`/`false` or `null`;
  a nested object or list is refused rather than reshaped.
</ParamField>

<ParamField body="scheduledAt" type="string">
  Don't ring before this moment — an instant **with its offset**, like
  `"2026-09-18T10:00:00+05:30"`. Up to 30 days ahead. The call is queued
  (`status: "scheduled"`) and rings at `scheduledAt` or, if that falls outside
  `callingHours`, at the next minute they open. A time already past means now.
  `ifOutsideHours: "refuse"` does not apply to a booked call.
</ParamField>

<ParamField body="retry" type="object">
  Try again when the person **was not reached**:

  ```json theme={null}
  { "count": 2, "noAnswerMinutes": 60, "busyMinutes": 15 }
  ```

  * `count` — further attempts after the first, 0–5.
  * `noAnswerMinutes` — wait after a call nobody answered, or an answering
    machine took. 5–1440, default 60.
  * `busyMinutes` — wait after an engaged line. 5–1440, default 15.

  A declined call, a number that does not exist and a call somebody answered
  are **never** retried, whatever `count` says. A retry keeps the same `id`,
  still rings only inside `callingHours`, and is checked again for opt-outs
  and the do-not-call list when it is due.
</ParamField>

<ParamField body="from" type="string">
  Which of the agent's numbers rings the customer: its own number, or one lent
  to it for calling on the **Phone Numbers** page.
  [`GET /api/v1/phone-numbers`](/api-reference/voices-and-models) lists them.
  Spaces and `+` are fine. Leave it out for the agent's own number. The agent's
  numbers can be on different phone companies — a number from us and one you
  imported from Twilio, say — and the call goes out through the chosen number's
  own company, on its own account.

  A number you choose, on an agent with more than one, may place **200 calls a
  day** — the limit that keeps a number from being flagged as spam. Past it the
  request answers `429`; a queued call waits an hour and tries again. A number
  taken off the agent after a call was booked is not swapped for another: that
  call fails and says why.
</ParamField>

<ParamField body="overrides" type="object">
  Changes to the agent **for this call only**. The agent itself is not edited,
  and the next call sounds like it again.

  * `voice` — a voice id from [`GET /api/v1/voices`](/api-reference/voices-and-models).
    A premium voice bills this call at the premium rate.
  * `language` — a language the console offers, e.g. `"Hindi"`. What the call
    is heard and spoken in.
  * `maxCallSeconds` — 60 to 1200.
  * `callInstructions` — replaces the agent's **call instructions** (the box on
    its Voice page) for this call, up to 4,000 characters.

  Anything else is refused by name. To change what the agent says first, change
  `purpose` — it is already per call.
</ParamField>

## Who you may call

<AccordionGroup>
  <Accordion title="Anyone who has not told you to stop">
    A number that is not a contact yet is **accepted** and becomes one, with
    the `name` and `source` you sent. Nothing is created for a request that is
    refused.
  </Accordion>

  <Accordion title="Not somebody who opted out">
    A customer who withdrew consent is refused, whichever channel they said it
    on — including a phone call they took from your agent.

    ```json theme={null}
    { "error": "That customer has asked not to be contacted." }
    ```
  </Accordion>

  <Accordion title="Not a number on your do-not-call list">
    Numbers on your workspace's do-not-call list are refused.

    ```json theme={null}
    { "error": "That number is on your do-not-call list." }
    ```
  </Accordion>
</AccordionGroup>

<Warning>
  **These rules are ours, not your regulator's.** Passing them does not mean a
  call is lawful where you operate. In India that means TRAI's rules, DND
  registers and DLT registration for anything promotional.

  You are responsible for having a lawful basis for each call. Somebody who
  filled in your enquiry form a minute ago sits very differently from a number
  on a bought list — `source` is where you record which it was.
</Warning>

## Responses

<ResponseField name="202 Accepted" type="object">
  `status: "ringing"` — the call is being placed now. `id` starts `out_`.

  `status: "scheduled"` — it is outside the hours you gave, so the call is
  queued. `id` starts `sch_` and `scheduledFor` says when it will ring.
  `from` is the number you chose, or `null` when the agent's own number will
  be used. It is
  placed then with the same checks, and if it still cannot be placed after three
  tries you are told through `call.analysed` with `status: "failed"`.
</ResponseField>

<ResponseField name="400" type="object">
  A missing `to` or `purpose`, a number that could not be read, a purpose over
  300 characters, several phone agents and no `agent`, a `from` that is not
  one of the agent's numbers, a voice we do not offer, or any optional field
  that does not follow the rules above. The `error` says which. Nothing is
  created for a refused request.
</ResponseField>

<ResponseField name="403" type="object">
  The customer opted out, or the number is on your do-not-call list.
</ResponseField>

<ResponseField name="409" type="object">
  * Outside calling hours with `ifOutsideHours: "refuse"` — carries
    `nextOpening`.
  * Hours that can never open for this number (a one-hour window across a
    country with several time zones).
  * A call to this number is already waiting on this agent — booked, queued
    for its hours, or a retry — carries that call's `id` and `scheduledFor`.
  * The person is on a call with this agent right now.
  * No agent answers the phone, or the only number is one you brought without
    adding its carrier credentials.
  * `from` is one of the agent's numbers that you brought without adding its
    carrier credentials — add them on the **Phone Numbers** page. A call is never
    placed on another account instead.
  * The same `Idempotency-Key` is still being processed.
</ResponseField>

<ResponseField name="429" type="object">
  Too many calls a minute, or the workspace already has as many calls running as
  it is allowed — both carry `Retry-After` — or the `from` you chose has
  placed its calls for today.
</ResponseField>

<ResponseField name="502 / 503" type="object">
  Your phone provider would not place the call. `503` means it is refusing
  everything right now and is worth retrying; `502` means this number.
</ResponseField>

## Not calling twice

Send an `Idempotency-Key`, derived from the lead or the reason for the call —
never a random value.

```
Idempotency-Key: lead-LSQ-42
```

A repeat of that key places **no second call** and answers with the first reply
— the same `id`, scheduled or ringing. A body field named `idempotencyKey` works
too; the header wins if you send both. Keys are honoured for 24 hours.

Even without a key, a person is never rung twice at once: a request for somebody
who already has a call waiting on the same agent — booked, queued or a retry —
is refused with that call's `id`, and so is one for somebody on a call with the
agent right now. A CRM that fires "lead created" twice does not ring anyone twice.

## What happens after

The call appears in your inbox against that customer, with its transcript.

To get the result into your own system, either:

* subscribe an endpoint to **A call's results are ready** (`call.analysed`) on
  the agent's **Actions** page — it is sent once the summary and fields are
  written, or
* read [`GET /api/v1/calls/{id}`](/api-reference/get-call) with the `id` you got
  back.

**A call finished** (`call.completed`) still arrives the moment the call ends,
before anything has been read. For an API call it now also carries your `id`
and `reference`.

<Note>
  Calls placed this way count toward the same concurrency ceiling as calls
  people make to you. Ringing a list? Use [`POST /api/v1/calls/batch`](/api-reference/batch-calls)
  and let us pace it.
</Note>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.