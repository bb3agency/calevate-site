> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Enrol in a sequence

> POST /api/v1/sequences/{id}/enrolments — put one person into a sequence, with their own data.

```http theme={null}
POST /api/v1/sequences/8f21c0d4-…/enrolments
Authorization: Bearer ta_live_…
Content-Type: application/json
```

```json theme={null}
{
  "to": "919876543210",
  "variables": { "order": "1042", "eta": "Thursday" }
}
```

This is what an order webhook from your own system calls when it knows exactly
which sequence it wants. The variables ride along with the enrolment, so a
message three days later can still say the order number — the console has no
idea what that is, which is the whole reason the field exists.

<Warning>
  **Prefer [Report an event](/api-reference/report-event) unless you have a
  reason not to.** This endpoint puts a sequence's id in your code. Rebuild the
  sequence and this call stops working; change which follow-up runs and somebody
  has to deploy.

  Use this one when the choice genuinely belongs to your system — a plan-specific
  onboarding, say, where your backend already knows which of five journeys
  applies.
</Warning>

## Path

<ParamField path="sequenceId" type="string" required>
  The sequence's id, from its page in the console.
</ParamField>

## Body

<ParamField body="to" type="string" required>
  The number to enrol. E.164, with or without the `+`.

  **They must already be a contact.** This does not create one — see the
  response below.
</ParamField>

<ParamField body="variables" type="object">
  Values the sequence's messages can use, as names to strings.

  At most **20**, each name up to **60** characters and each value up to **300**.
  Over any of those is refused rather than trimmed, because a shortened name
  would leave a template reading a blank that no longer exists.
</ParamField>

## Response

```json theme={null}
{ "enrolled": true, "id": "3c0b…" }
```

```json theme={null}
{
  "enrolled": false,
  "reason": "Already in this sequence, not a known contact, opted out, or the sequence has no first message yet."
}
```

<Note>
  **`enrolled: false` is a 200, not an error.** Four things produce it — they are
  already in this sequence, the number is not a contact, they have opted out, or
  the sequence has no first message yet — and none of them is a failure of your
  request.

  A `4xx` here would have a webhook retrying all four for ever, which is the one
  thing that turns "already enrolled" from a shrug into an incident.
</Note>

<Warning>
  **Opt-in is your responsibility on this endpoint.** WhatsApp only allows a
  business to message someone who gave you their number **and** agreed to hear
  from you. Calling this endpoint is you telling us they did, so we do not check
  it here — only enrol people you have opt-in for. Anyone who has opted out is
  always refused, and anyone who opts out mid-sequence stops receiving it.
</Warning>

## Errors

| Status | When |
| - | - |
| `400` | `to` missing, `variables` not an object, or a cap exceeded |
| `401` | The key is missing, wrong, or revoked |
| `404` | No sequence with that id on your workspace |
| `500` | We could not enrol them — safe to retry |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.