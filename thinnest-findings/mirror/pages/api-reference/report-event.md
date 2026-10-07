> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Report an event

> POST /api/v1/events — tell us something happened, and we decide what to send.

```http theme={null}
POST /api/v1/events
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "to": "919876543210",
  "event": "order.delivered",
  "data": { "order": "1042", "courier": "Bluedart" }
}
```

## The difference between this and Send a message

This is the one worth understanding before you pick an endpoint, because it
decides which of your systems owns a marketing decision.

<CardGroup cols={2}>
  <Card title="Send a message" icon="paper-plane" href="/api-reference/send-message">
    **"Send this now."** You chose the template and the moment. An order
    confirmation goes out when the order is confirmed — nobody is going to
    change their mind about that.
  </Card>

  <Card title="Report an event" icon="bell">
    **"This just happened."** We choose, from what you set up in the console. A
    review request three days after delivery is this one: your code knows the
    parcel arrived and nothing else.
  </Card>
</CardGroup>

<Tip>
  **Why not have your code enrol people in a sequence directly?** Because that
  welds a sequence's id into your deploy. Rebuild the sequence and your code
  quietly stops working, and changing which message fires needs an engineer.

  Posting an event name inverts it: your code says what happened, the console
  says what happens next. Marketing can change the follow-up on a Tuesday
  afternoon without touching your backend.
</Tip>

## Body

<ParamField body="to" type="string" required>
  The customer's number. E.164, with or without the `+`; spaces are fine.

  Normalised the same way the contact importer is, so `+91 98765 43210` and
  `919876543210` are the same person rather than two.
</ParamField>

<ParamField body="event" type="string" required>
  What happened, as a name — `order.delivered`, `trial.ended`,
  `cart.abandoned`.

  **Normalised, and the response tells you how.** "Order Delivered" is stored as
  `order.delivered`. Read the `event` field that comes back and use exactly that
  when you set the subscription up in the console, or the two will never match.
</ParamField>

<ParamField body="data" type="object">
  Values to carry into whatever this triggers — an order number, a courier, a
  date. Names to strings.

  At most **20 values**, each name up to **60 characters** and each value up to
  **300**. Over any of those is refused rather than trimmed: a shortened name
  would silently stop matching the template that reads it.
</ParamField>

<ParamField body="name" type="string">
  The customer's name, if you have it and we might not. Used when the contact is
  created by this call.
</ParamField>

## Response

```json theme={null}
{
  "ok": true,
  "event": "order.delivered",
  "contact": "6f3a…",
  "started": 1,
  "stopped": 0,
  "tagged": 1,
  "matched": true
}
```

<ResponseField name="event" type="string">
  The normalised name. Configure your subscription against **this**, not what
  you sent.
</ResponseField>

<ResponseField name="started" type="number">
  Sequences this event enrolled the contact into.
</ResponseField>

<ResponseField name="stopped" type="number">
  Sequences it took them out of. A delivery event usually ends the "where is my
  order" chase.
</ResponseField>

<ResponseField name="tagged" type="number">
  Tags added to the contact.
</ResponseField>

<ResponseField name="matched" type="boolean">
  Whether anything was listening.
</ResponseField>

<Note>
  **Nothing listening is still a 200**, with `matched: false` and a `note`
  saying so. The contact and the event are recorded either way.

  This is deliberate: you should be able to start sending events before anyone
  has configured what they do, and adding the subscription later must not
  require a deploy on your side. A 404 here would have your webhook retrying
  for ever over a decision nobody has made yet.
</Note>

<Warning>
  **Opt-in is your responsibility when an event starts a sequence.** WhatsApp only
  allows a business to message someone who gave you their number **and** agreed
  to hear from you. Sending an event for a customer is you telling us they did, so
  a subscribed sequence starts without us checking it — only send events for
  people you have opt-in for. Anyone who has opted out is never enrolled, and
  anyone who opts out mid-sequence stops receiving it.
</Warning>

## Errors

| Status | When |
| - | - |
| `400` | `to` or `event` missing, `data` not an object, or a cap exceeded |
| `401` | The key is missing, wrong, or revoked |
| `500` | We could not record it — safe to retry |

See [Errors](/api-reference/errors) for the shape.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.