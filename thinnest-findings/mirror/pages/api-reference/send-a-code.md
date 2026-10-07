> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Send a one-time code

> Authentication templates — what Meta writes for you, and the one thing everybody gets wrong.

```http theme={null}
POST /api/v1/codes
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "to": "919876543210",
  "code": "394812"
}
```

That is the whole request. You generated the code; we find your approved
authentication template, put the code where Meta needs it — **including in the
button, which is the part everybody gets wrong** — and send it.

<Check>
  **We do not generate, store, expire or check the code.** That stays yours.
  This endpoint delivers a code you already own, which is the honest description
  of what it does.
</Check>

## Body

<ParamField body="to" type="string" required>
  The number to send it to. E.164 — **include the `+` and the country code** (a leading `00` works too). Without a `+`, a number of ten digits or fewer is read as an Indian number and `91` is added, so a number from anywhere else sent bare would go to the wrong country.
</ParamField>

<ParamField body="code" type="string" required>
  The code you generated. Sixteen characters at most — beyond that it is almost
  always the wrong field, and a JWT in front of a customer as "your verification
  code" is worse than a refusal.
</ParamField>

<ParamField body="template" type="string">
  Which code template to use. Only needed when you have more than one approved —
  a second language, say. With one, we use it.
</ParamField>

<ParamField body="language" type="string">
  Narrows the choice when you keep the same template name in several languages.
</ParamField>

## Response

```json theme={null}
{
  "sent": true,
  "to": "919876543210",
  "template": "login_code",
  "language": "en_US",
  "messageRef": "wamid.HBgM…"
}
```

| Status | When |
| - | - |
| `400` | `to` or `code` missing, unreadable, or the code is too long |
| `404` | No approved authentication template yet — make one under **One-Time Codes** |
| `409` | More than one approved template and you did not say which. The response lists them |
| `409` | The number is restricted, or the template carries something a send cannot fill |
| `429` | Too many API sends this minute. `Retry-After: 60` |
| `502` | WhatsApp accepted nothing this time — a transient failure, safe to retry |
| `503` | WhatsApp is not connected yet |

<Note>
  **Retry on `429` and `502`, never on a `4xx` that is not one of them.** A
  `400` means the request will fail identically however many times you send it;
  a `502` means the moment was bad and the next one may not be.
</Note>

<Note>
  **A 409 rather than a guess.** With two approved templates and no `template`,
  choosing for you means choosing which language somebody reads their login code
  in. That is not a decision to make quietly, and it is one line of code to make
  explicit.

  If you have **one name approved in several languages**, `template` narrows
  nothing — the response says so and asks for `language` instead.
</Note>

<Warning>
  **There is a ceiling on sends per minute**, shared with `/api/v1/messages` and
  `/api/v1/calls`. Codes are allowed the higher share of it, so a batch of order
  confirmations cannot stop people logging in — but a login screen retried in a
  loop still meets it, and past it nothing goes out at all. Meta charges per
  message, and authentication is its dearest category.
</Warning>

## Not sending the same code twice

Two different things go wrong here and each needs its own answer.

### A retry of the same request

Send an `Idempotency-Key`.

```
Idempotency-Key: login-8891-attempt-1
```

A repeat of that key sends nothing and answers with **the first reply, exactly
as it was** — the same status, the same recipient, template and language, whether
that first reply was a success or a refusal. The only difference is a header:

```
Idempotent-Replayed: true
```

A body field named `idempotencyKey` works too; the header wins if you send both.

<Warning>
  **Derive the key from the login attempt, not from a random value.** Your
  retry, your queue's redelivery and a user's double-tap have to produce the
  same key or there is nothing to match on. A UUID generated per attempt never
  repeats and therefore never protects anything.
</Warning>

Keys are honoured for **24 hours**, which is long enough for any retry worth
making. After that the same string is a new request and sends again — so if you
reuse a stable key like `login-8891`, be aware that tomorrow's login for that
same session id will go out rather than replay.

<Note>
  If a request carrying that key is **still in flight**, the second one gets
  `409` rather than a second code. Retry after a moment and it will have an
  answer to give you.
</Note>

### The same person asking again

An idempotency key cannot help with this one, and it is the failure OTP
endpoints actually have. Five different requests for one number — somebody
tapping **Resend**, or a login screen looping — are five different requests, and
each is legitimately asking for a new code.

So there is a second limit: **five codes to one number in ten minutes.** Past
it, `429` with a `Retry-After` saying when the window clears.

```json theme={null}
{ "error": "That number has already been sent 5 codes in the last 10 minutes." }
```

<Check>
  This is Twilio Verify's number, not one we invented — the same five-in-ten
  that their `60203` refuses at. It is enough for a person who genuinely mistyped
  their number twice, and not enough to be worth abusing.
</Check>

<Warning>
  **Put a resend cooldown in your own interface too.** A greyed-out button for
  thirty seconds stops the loop before it reaches us; this limit is the floor
  under that, not a substitute for it. Authentication is Meta's dearest category
  and every one of those five is charged.
</Warning>

## Or through the general endpoint

`POST /api/v1/messages` still works — an authentication template is a template —
and you would name it yourself:

```json theme={null}
{
  "to": "919876543210",
  "template": "login_code",
  "variables": ["394812"]
}
```

<Check>
  **Pass the code once, in `variables`.** Do not also put it in
  `buttonVariables` — we copy it into the button for you. See below for why that
  matters.
</Check>

## You do not write an authentication template

This surprises people, and it is a mercy rather than a restriction. Meta writes
the body:

> **394812** is your verification code. For your security, do not share this code.
>
> *Expires in 10 minutes.*

You cannot change that wording, add your brand to it, or explain anything in it.
OTP is the one message where wording is a liability, and Meta has already argued
with every phishing pattern there is.

Templates are created, submitted and deleted in the console — see
[One-time codes](/whatsapp/one-time-codes). There is no API for managing them,
deliberately: a template is reviewed by Meta and lives for months, so it is not
something a deploy should be creating on the fly.

What you **do** choose, on the **One-Time Codes** page in the console:

<ParamField path="Security line" type="on / off">
  Appends *"For your security, do not share this code."* On by default.
</ParamField>

<ParamField path="Expiry" type="1–90 minutes">
  Shown to the customer in their own language, by Meta. Ten minutes by default:
  long enough to find your phone, short enough that a screenshot in a group chat
  is worthless by the time it matters.
</ParamField>

<ParamField path="Button" type="Copy code / One-tap">
  How the code gets out of WhatsApp and into your app.

  * **Copy code** — they tap, then paste. Works everywhere, needs no
    integration. This is the default and the right answer for almost everyone.
  * **One-tap autofill** — hands the code straight to your Android app. Needs
    your app's package name and signing hash, which the form asks for.

  There is no third option. Meta requires exactly one button on a code
  template, and it must be one of these two.
</ParamField>

## The thing everybody gets wrong

**A copy-code button does not read the code out of the message.** Meta treats
the body and the button as separate components, and the code has to be supplied
to both. Send it only in the body and the button copies nothing — the customer
taps it, gets an empty clipboard, and blames your app.

We do this for you: when the template is an authentication one with a code
button, the value you put in `variables[0]` is sent to the button as well.

<Warning>
  Which is also why you should **not** pass `buttonVariables` on an
  authentication template. We already put the code where the button needs it,
  and a second value for the same button is a parameter Meta cannot place:

  ```
  (#132018) There's an issue with the parameters in your template
  ```

  The message does not arrive at all, and nothing about the error says which
  field caused it.
</Warning>

## Costs

Authentication is priced separately from marketing and utility, and
**a code sent to another country costs many times what a domestic one does** —
on Meta's Indian card the difference is more than twentyfold. Meta treats
international authentication as its own category, so this is not a rounding
difference you can ignore.

Your actual figures are on the [usage page](/workspace/usage), itemised by
category and country. Read them there rather than from any rate you have been
quoted: a login flow that has quietly gone global shows up as a line, which is
the only way anyone notices in time.

<Note>
  Codes are not a good fit for a [sequence](/whatsapp/sequences) or a
  [broadcast](/whatsapp/broadcasts). They are transactional by definition — one
  code, one moment, one person — which is exactly what this endpoint is for.
</Note>

## Errors

The usual [errors](/api-reference/errors) apply. Two are specific to codes:

| What you see | What it means |
| - | - |
| `(#132018) There's an issue with the parameters` | Usually `buttonVariables` sent alongside `variables` — leave it out entirely on a code template |
| Template not approved | Authentication templates go through review like any other, and a fresh one cannot send until Meta has looked at it |
| Suddenly `404` on a name that worked | Somebody deleted the template. Deleting removes it from Meta as well, and Meta holds the name for 30 days — so the replacement needs a different name |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.